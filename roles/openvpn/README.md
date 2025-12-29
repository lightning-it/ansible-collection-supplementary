Role Name
=========

A brief description of the role goes here.

Requirements
------------

Any pre-requisites that may not be covered by Ansible itself or the role should be mentioned here. For instance, if the role uses the EC2 module, it may be a good idea to mention in this section that the boto package is required.

Role Variables
--------------

A description of the settable variables for this role should go here, including any variables that are in defaults/main.yml, vars/main.yml, and any variables that can/should be set via parameters to the role. Any variables that are read from other roles and/or the global scope (ie. hostvars, group vars, etc.) should be mentioned here as well.

Dependencies
------------

A list of other roles hosted on Galaxy should go here, plus any details in regards to parameters that may need to be set for other roles, or variables that are used from other roles.

Example Playbook
----------------

Including an example of how to use your role (for instance, with variables passed in as parameters) is always nice for users too:

    - hosts: servers
      roles:
         - { role: username.rolename, x: 42 }

License
-------

BSD

Author Information
------------------

An optional section for the role authors to include contact information, or a website (HTML is not allowed).



TODOS


# SRC: https://blog.thinkbox.dev/posts/0001-openvpn-ldap-auth/
dnf install -y google-authenticator
mkdir /etc/openvpn/otp

/etc/pam.d/openvpn
auth required pam_google_authenticator.so secret=/etc/openvpn/otp/${USER}.google_authenticator user=root forward_pass
auth required pam_ldap.so use_first_pass

account sufficient pam_permit.so

# Create a OTP setting for a user.
export USER="bdr01"
google-authenticator \
                     --time-based \
                     --disallow-reuse \
                     --force \
                     --no-confirm \
                     --rate-limit=3 \
                     --rate-time=30 \
                     --window-size=3 \
                     -l "${USER}@dc01.core.corp.l-it.io" \
                     -s /etc/openvpn/otp/${USER}.google_authenticator
# In order to disable renegotiation set the following in /etc/openvpn/server/openvpn_udp_1194.conf and user config.
reneg-sec 0


#selinux
cd /etc/openvpn/otp
chcon -u system_u -t openvpn_etc_rw_t tim.google_authenticator

systemctl restart openvpn-server@openvpn_udp_1194.service