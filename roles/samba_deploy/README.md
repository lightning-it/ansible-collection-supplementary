# samba_deploy

Deploy Samba as a Podman container from a rendered pod manifest and expose a
host-mounted share directory.

Set `samba_deploy_mode: ad_dc` to run a lightweight Samba AD/LDAPS container
for application authentication tests. In this mode the role exposes LDAP/LDAPS,
persists Samba state directories, and can bootstrap a Keycloak bind user.

AD mode also seeds default application groups and users through
`samba_deploy_ad_dc_groups` and `samba_deploy_ad_dc_users`. The defaults create
`admins`, `managers`, and `viewers` with one sample user in each group. Override
those lists in inventory when an app needs a different authorization model.
