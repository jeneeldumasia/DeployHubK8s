@echo off
docker exec desktop-control-plane sh -c "mkdir -p /etc/containerd/certs.d/registry:5000 && printf 'server = \"http://registry:5000\"\n\n[host.\"http://registry:5000\"]\n  capabilities = [\"pull\", \"resolve\"]\n  skip_verify = true\n' > /etc/containerd/certs.d/registry:5000/hosts.toml"
docker exec desktop-control-plane sh -c "mkdir -p /etc/containerd/certs.d/10.96.131.7:5000 && printf 'server = \"http://10.96.131.7:5000\"\n\n[host.\"http://10.96.131.7:5000\"]\n  capabilities = [\"pull\", \"resolve\"]\n  skip_verify = true\n' > /etc/containerd/certs.d/10.96.131.7:5000/hosts.toml"
docker exec desktop-control-plane cat /etc/containerd/certs.d/registry:5000/hosts.toml
