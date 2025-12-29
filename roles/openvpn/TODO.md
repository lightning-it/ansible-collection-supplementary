# ansible-role-openvpn


vpn01:
[root@vpn01 ~]# cat /etc/sysconfig/network-scripts/route-ens192 
ADDRESS0=10.10.31.0
NETMASK0=255.255.255.0
GATEWAY0=10.10.30.1
ADDRESS1=10.10.32.0
NETMASK1=255.255.255.0
GATEWAY1=10.10.30.1
ADDRESS2=10.10.33.0
NETMASK2=255.255.255.0
[root@vpn01 ~]# 

[root@vpn01 ~]# cat /etc/sysconfig/network-scripts/ifcfg-ens192 
TYPE=Ethernet
PROXY_METHOD=none
BROWSER_ONLY=no
BOOTPROTO=none
DEFROUTE=no
IPV4_FAILURE_FATAL=no
IPV6INIT=no
IPV6_DEFROUTE=yes
IPV6_FAILURE_FATAL=no
NAME=ens192
UUID=1781f6eb-1606-4a88-b8da-3de8dd5462be
DEVICE=ens192
ONBOOT=yes
IPV6_DISABLED=yes
IPADDR=10.10.30.200
PREFIX=24
DNS1=10.10.30.3
[root@vpn01 ~]# 




###DONE
cat <<EOF> /etc/openvpn/server/server.conf
# tun-style tunnel
port 1194
proto tcp
dev tun

# Subnet topology is the current recommended topology; 
topology subnet

# TLS parms
tls-server 
tls-version-min 1.2
crl-verify crl.pem
ca ca.crt
cert issued/vpn.hzn.cloud.l-it.io.crt
key private/vpn.hzn.cloud.l-it.io.key
dh dh.pem
tls-auth ta.key 0
auth SHA512

# Tell OpenVPN to be a multi-client udp server
mode server

# The server's virtual endpoints
server 10.10.200.0 255.255.255.0

# Custom routes behind vpn01
route 10.10.30.0 255.255.255.0
route 10.10.31.0 255.255.255.0
route 10.10.32.0 255.255.255.0
route 10.10.33.0 255.255.255.0
route 172.16.30.0 255.255.255.0

# Custom routes
client-to-client
push "route 192.168.253.64 255.255.255.255"
push "route 172.16.30.0 255.255.255.0"
push "route 10.10.30.0 255.255.255.0"
push "route 10.10.31.0 255.255.255.0"
push "route 10.10.32.0 255.255.255.0"
push "route 10.10.33.0 255.255.255.0"

# Client should attempt reconnection on link
# failure.
keepalive 10 60

# Delete client instances after some period
# of inactivity.
inactive 600

# The server doesn't need privileges
user openvpn
group openvpn

# Keep TUN devices and keys open across restarts.
persist-tun
persist-key

# Client configuration directory
client-config-dir /etc/openvpn/ccd

status /var/log/openvpn/status.log
log /var/log/openvpn/openvpn.log
verb 4

EOF

### config
cat <EOF> /etc/openvpn/client/client.conf 
client
dev tun

proto tcp
remote vpn.hzn.cloud.l-it.io 1194

keepalive 10 60

# Try to preserve some state across restarts.
persist-key
persist-tun

ca ca.crt
cert issued/vpn01.core.corp.l-it.io.crt
key private/vpn01.core.corp.l-it.io.key
tls-auth ta.key 1
auth SHA512

verb 3
EOF
