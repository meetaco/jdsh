# Needs validation

## jdsh:local-api:remote-exposure — Remote JDownloader Local API exposure may permit unauthorized queue control

**Status:** unresolved; no severity assigned.

JDSH's README describes enabling the deprecated Local API and notes localhost-only mode may need to be disabled for remote use. JDSH connects to a host and port from local configuration and exposes queue/download controls. Source review cannot establish whether the deployed JDownloader version requires authentication, binds to a reachable interface, or is reachable through firewall/routing policy.

**Safe validation:** On an isolated staging instance matching deployed version/configuration, confirm authentication requirements and listener/firewall exposure. If authorized, use a separate test host and dummy queue to make one read request and one harmless reversible operation. Do not test production or shared instances.
