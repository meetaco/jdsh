"""Human-facing diagnostics derived from JDownloader link state.

The API exposes several independent pieces of state rather than one canonical
"why is this not downloading?" field. Keep the raw values available elsewhere
and use this module only to build an explicitly sourced explanation.
"""


ADVANCED_REASON_KEYS = (
    "PluginProgress",
    "ConditionalSkipReason",
    "SkipReason",
    "FinalLinkState",
)


def available_status(link):
    advanced = link.get("advancedStatus") if link else None
    if not isinstance(advanced, dict):
        return None
    status = advanced.get("AvailableStatus")
    return status if isinstance(status, dict) else None


def availability_label(link):
    status = available_status(link) or {}
    status_id = status.get("id")
    label = status.get("label")
    if status_id and label and str(status_id) != str(label):
        return f"{status_id} ({label})"
    return str(status_id or label or "UNKNOWN")


def _reason_text(value):
    if isinstance(value, dict):
        for key in ("label", "message", "id", "reason"):
            if value.get(key) not in (None, ""):
                return str(value[key])
        return str(value)
    if value in (None, ""):
        return None
    return str(value)


def _advanced_reason(link):
    advanced = link.get("advancedStatus") if link else None
    if not isinstance(advanced, dict):
        return None, None
    for key in ADVANCED_REASON_KEYS:
        if key in advanced and advanced[key] not in (None, {}, []):
            return key, advanced[key]
    return None, None


def diagnose_link(link, controller_state=None):
    """Return a conservative diagnosis with its provenance.

    ``source`` is one of:
    - ``jdownloader``: directly backed by a link/controller field returned by JD.
    - ``inferred``: a safe combination of multiple returned fields.
    - ``unknown``: JD exposes no reason that explains the idle link.
    """
    if not link:
        return {
            "state": "UNKNOWN",
            "reason": "Download link data is unavailable.",
            "source": "unknown",
            "evidence": {},
        }

    status = link.get("status")
    advanced_key, advanced_value = _advanced_reason(link)
    availability = available_status(link) or {}
    availability_id = availability.get("id")
    evidence = {
        "status": status,
        "advancedStatusKey": advanced_key,
        "availability": availability_id,
        "running": link.get("running"),
        "enabled": link.get("enabled"),
        "skipped": link.get("skipped"),
        "finished": link.get("finished"),
    }
    if controller_state is not None:
        evidence["controllerState"] = str(controller_state)

    if link.get("running"):
        return {
            "state": "RUNNING",
            "reason": _reason_text(status) or "The link is currently running.",
            "source": "jdownloader",
            "evidence": evidence,
        }

    if link.get("finished"):
        return {
            "state": "FINISHED",
            "reason": _reason_text(status) or "JDownloader marks the link as finished.",
            "source": "jdownloader",
            "evidence": evidence,
        }

    if link.get("enabled") is False:
        return {
            "state": "DISABLED",
            "reason": "The download link is disabled.",
            "source": "jdownloader",
            "evidence": evidence,
        }

    if advanced_key:
        state_by_key = {
            "PluginProgress": "PROCESSING",
            "ConditionalSkipReason": "WAITING",
            "SkipReason": "SKIPPED",
            "FinalLinkState": "FINAL",
        }
        return {
            "state": state_by_key[advanced_key],
            "reason": _reason_text(advanced_value) or advanced_key,
            "source": "jdownloader",
            "evidence": evidence,
        }

    if link.get("skipped"):
        return {
            "state": "SKIPPED",
            "reason": "JDownloader marks the link as skipped but exposes no detailed SkipReason.",
            "source": "jdownloader",
            "evidence": evidence,
        }

    if availability_id == "FALSE":
        return {
            "state": "OFFLINE",
            "reason": "JDownloader reports the link as unavailable/offline.",
            "source": "jdownloader",
            "evidence": evidence,
        }

    if status not in (None, ""):
        return {
            "state": "STATUS",
            "reason": str(status),
            "source": "jdownloader",
            "evidence": evidence,
        }

    normalized_controller = str(controller_state).upper() if controller_state is not None else None
    if normalized_controller in {"STOPPED", "STOPPED_STATE", "PAUSED", "PAUSE"}:
        return {
            "state": "WAITING",
            "reason": f"The download controller is {controller_state}.",
            "source": "inferred",
            "evidence": evidence,
        }

    if link.get("enabled") and not link.get("finished"):
        return {
            "state": "WAITING",
            "reason": (
                "No link-level reason is exposed by JDownloader. The link is enabled, "
                "not finished, and not currently running."
            ),
            "source": "unknown",
            "evidence": evidence,
        }

    return {
        "state": "UNKNOWN",
        "reason": "JDownloader does not expose enough state to explain this link.",
        "source": "unknown",
        "evidence": evidence,
    }
