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

{{- define "edge-runtime-rust.validate" -}}
{{- if ne .Values.mode "legacy" -}}
{{- fail "This runtime only runs agent bundles, mode must be legacy. Use infra/helm/edge-runtime for gateway mode." -}}
{{- end -}}
{{- if and (not .Values.signing_pubkey) (not (eq (toString .Values.allow_unsigned) "true")) -}}
{{- fail "signing_pubkey is required. Fetch it from GET /api/edge/signing-key on the platform. allow_unsigned=true bypasses this for local development only." -}}
{{- end -}}
{{- end }}

{{- define "edge-runtime-rust.literalTrue" -}}
{{- if eq (toString .) "true" -}}true{{- else -}}false{{- end -}}
{{- end }}
