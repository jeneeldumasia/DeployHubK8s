import re

with open("k8s_deploy/overlays/k3s/monitoring.yaml", "r") as f:
    content = f.read()

# 1. Add Scrape Configs
scrape_addition = """          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
            action: keep
            regex: "true"

      # Scrape Kubernetes Nodes (kubelet) for Node-level metrics
      - job_name: kubernetes-nodes
        scheme: https
        tls_config:
          ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
          insecure_skip_verify: true
        bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
        kubernetes_sd_configs:
          - role: node
        relabel_configs:
          - action: labelmap
            regex: __meta_kubernetes_node_label_(.+)

      # Scrape cAdvisor for Per-Pod/Container resource metrics
      - job_name: kubernetes-cadvisor
        scheme: https
        tls_config:
          ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
          insecure_skip_verify: true
        bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
        kubernetes_sd_configs:
          - role: node
        relabel_configs:
          - action: labelmap
            regex: __meta_kubernetes_node_label_(.+)
          - target_label: __metrics_path__
            replacement: /metrics/cadvisor
"""
content = re.sub(r'          - source_labels: \[__meta_kubernetes_pod_annotation_prometheus_io_scrape\]\n            action: keep\n            regex: "true"\n', scrape_addition, content)

# 2. Add Prometheus RBAC
rbac_addition = """---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus
  namespace: deployhub
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus
rules:
  - apiGroups: [""]
    resources:
      - nodes
      - nodes/metrics
      - nodes/proxy
      - services
      - endpoints
      - pods
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources:
      - configmaps
    verbs: ["get"]
  - nonResourceURLs: ["/metrics"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: prometheus
subjects:
  - kind: ServiceAccount
    name: prometheus
    namespace: deployhub
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: prometheus-data-pvc"""
content = re.sub(r'---\napiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: prometheus-data-pvc', rbac_addition, content)

# 3. Add Service Account Name to Deployment
content = re.sub(r'    spec:\n      containers:', '    spec:\n      serviceAccountName: prometheus\n      containers:', content)

# 4. Add Grafana Embed Env Vars
grafana_env = """            - name: GF_AUTH_ANONYMOUS_ORG_NAME
              value: "Main Org."
            - name: GF_AUTH_ANONYMOUS_HIDE_VERSION
              value: "true"
            - name: GF_SECURITY_ALLOW_EMBEDDING
              value: "true"
"""
content = re.sub(r'            - name: GF_AUTH_ANONYMOUS_ORG_NAME\n              value: "Main Org."\n', grafana_env, content)

# 5. Add Volume Mounts
volume_mounts = """            - name: grafana-dashboard-app-overview
              mountPath: /etc/grafana/dashboards/app-overview
            - name: grafana-dashboard-node-overview
              mountPath: /etc/grafana/dashboards/node-overview
            - name: grafana-dashboard-pod-overview
              mountPath: /etc/grafana/dashboards/pod-overview
"""
content = re.sub(r'            - name: grafana-dashboard-app-overview\n              mountPath: /etc/grafana/dashboards/app-overview\n', volume_mounts, content)

# 6. Add Volumes
volumes = """        - name: grafana-dashboard-app-overview
          configMap:
            name: grafana-dashboard-app-overview
        - name: grafana-dashboard-node-overview
          configMap:
            name: grafana-dashboard-node-overview
        - name: grafana-dashboard-pod-overview
          configMap:
            name: grafana-dashboard-pod-overview
"""
content = re.sub(r'        - name: grafana-dashboard-app-overview\n          configMap:\n            name: grafana-dashboard-app-overview\n', volumes, content)

with open("k8s_deploy/overlays/k3s/monitoring.yaml", "w") as f:
    f.write(content)
