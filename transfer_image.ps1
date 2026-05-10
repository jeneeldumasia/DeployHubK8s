docker pull node:20-alpine
docker save node:20-alpine -o node.tar
Get-Content node.tar -Raw | docker exec -i desktop-control-plane ctr -n k8s.io images import -
Remove-Item node.tar
