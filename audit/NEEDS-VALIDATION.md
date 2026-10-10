# Needs validation

## jdsh:local-api:remote-exposure — Remote JDownloader Local API exposure may permit unauthorized queue control

**Status:** unresolved; no severity assigned.

JDSH's README describes enabling the deprecated Local API and notes localhost-only mode may need to be disabled for remote use. A JDownloader project manager states that the deprecated API has no authentication or encryption by default ([official community guidance](https://board.jdownloader.org/showthread.php?p=547625)). JDSH connects to a host and port from local configuration and exposes queue/download controls. The unresolved fact is whether the deployed listener and firewall/VPN/routing policy make it reachable by a lower-trust principal.

**Safe validation:** On an isolated staging instance matching deployed version/configuration, confirm listener bind and firewall/VPN/SSH-tunnel exposure. If authorized, use a separate test host and dummy queue to make one read request and one harmless reversible operation. Do not test production or shared instances.
