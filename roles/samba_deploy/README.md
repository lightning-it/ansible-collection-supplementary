# samba_deploy

Deploy Samba as a Podman container from a rendered pod manifest and expose a
host-mounted share directory.

Set `samba_deploy_mode: ad_dc` to run a lightweight Samba AD/LDAPS container
for application authentication tests. In this mode the role exposes LDAP/LDAPS,
persists Samba state directories, and can bootstrap a Keycloak bind user.

AD mode seeds the application groups and users supplied through
`samba_deploy_ad_dc_groups` and `samba_deploy_ad_dc_users`. The defaults define
the `admins`, `managers`, and `viewers` groups but intentionally contain no user
or credential. Supply every administrator, bind, and user credential through a
protected secret source.
