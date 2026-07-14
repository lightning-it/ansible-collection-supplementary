# OpenVPN Operational Notes

These are unvalidated legacy notes retained for future role development. They
are not a supported deployment procedure.

## Example network configuration

```ini
# /etc/sysconfig/network-scripts/route-ens192
ADDRESS0=10.10.31.0
NETMASK0=255.255.255.0
GATEWAY0=10.10.30.1
ADDRESS1=10.10.32.0
NETMASK1=255.255.255.0
GATEWAY1=10.10.30.1
ADDRESS2=10.10.33.0
NETMASK2=255.255.255.0

# /etc/sysconfig/network-scripts/ifcfg-ens192
TYPE=Ethernet
BOOTPROTO=none
DEFROUTE=no
DEVICE=ens192
ONBOOT=yes
IPV6_DISABLED=yes
IPADDR=10.10.30.200
PREFIX=24
DNS1=10.10.30.3
```

## Example server configuration

```text
port 1194
proto tcp
dev tun
topology subnet
tls-server
tls-version-min 1.2
crl-verify crl.pem
ca ca.crt
cert issued/vpn.example.com.crt
key private/vpn.example.com.key
dh dh.pem
tls-auth ta.key 0
auth SHA512
mode server
server 10.10.200.0 255.255.255.0
route 10.10.30.0 255.255.255.0
route 10.10.31.0 255.255.255.0
route 10.10.32.0 255.255.255.0
route 10.10.33.0 255.255.255.0
client-to-client
push "route 192.0.2.64 255.255.255.255"
push "route 10.10.30.0 255.255.255.0"
push "route 10.10.31.0 255.255.255.0"
push "route 10.10.32.0 255.255.255.0"
push "route 10.10.33.0 255.255.255.0"
keepalive 10 60
inactive 600
user openvpn
group openvpn
persist-tun
persist-key
client-config-dir /etc/openvpn/ccd
status /var/log/openvpn/status.log
log /var/log/openvpn/openvpn.log
verb 4
```

## Example client configuration

```text
client
dev tun
proto tcp
remote vpn.example.com 1194
keepalive 10 60
persist-key
persist-tun
ca ca.crt
cert issued/client.example.com.crt
key private/client.example.com.key
tls-auth ta.key 1
auth SHA512
verb 3
```
