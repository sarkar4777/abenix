{{- define "testbed.labels" -}}
app.kubernetes.io/part-of: abenix-testbed
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "testbed.secret" -}}
valueFrom:
  secretKeyRef:
    name: {{ .root.Values.credentialsSecret }}
    key: {{ .key }}
{{- end }}
