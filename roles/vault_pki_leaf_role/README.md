# Vault PKI leaf role

Reconciles one explicitly supplied leaf role on an existing Vault PKI mount.
It does not create or rotate an issuer. The caller supplies temporary administrative
authorization, verified TLS trust and explicit change authorization; the caller
must revoke its administrative authorization in an enclosing `always` block.
Every declared leaf field is checked against an independent API readback.
