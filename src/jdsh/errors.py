"""Expected configuration and JDownloader operation failures."""


class JDShError(RuntimeError):
    """Base failure that can be presented by CLI or TUI."""


class ConfigError(JDShError):
    """Configuration could not be read or validated."""


class ServiceError(JDShError):
    """A JDownloader operation failed."""


class JDConnectionError(ServiceError):
    """A connection to JDownloader could not be established."""


class StatsError(ServiceError):
    """The download snapshot could not be fetched."""
