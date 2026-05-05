{{- define "edge-runtime-rust.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "edge-runtime-rust.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "edge-runtime-rust.labels" -}}
helm.sh/chart: {{ include "edge-runtime-rust.name" . }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ include "edge-runtime-rust.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
abenix.io/gateway-id: {{ .Values.gateway_id | quote }}
abenix.io/runtime-variant: rust
{{- end }}

{{- define "edge-runtime-rust.selectorLabels" -}}
app.kubernetes.io/name: {{ include "edge-runtime-rust.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
