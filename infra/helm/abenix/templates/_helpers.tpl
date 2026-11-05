{{- define "abenix.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "abenix.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "abenix.labels" -}}
helm.sh/chart: {{ include "abenix.name" . }}
app.kubernetes.io/name: {{ include "abenix.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/* Where backups go: backup.target.type, or the object storage backend, or local */}}
{{- define "abenix.backup.target" -}}
{{- $target := "" -}}
{{- with .Values.backup.target }}{{ $target = .type | default "" }}{{ end -}}
{{- $target | default (.Values.objectStorage.type | default "local") -}}
{{- end -}}

{{/* Environment for files/backup_store.py */}}
{{- define "abenix.backup.storeEnv" -}}
{{- $target := include "abenix.backup.target" . -}}
{{- if eq $target "s3" -}}
- name: BACKUP_STORE
  value: s3
- name: BACKUP_BUCKET
  value: {{ .Values.backup.s3Bucket | default .Values.objectStorage.bucket | default "" | quote }}
- name: STORAGE_S3_REGION
  value: {{ .Values.objectStorage.region | default "us-east-1" | quote }}
- name: STORAGE_S3_ENDPOINT
  value: {{ .Values.objectStorage.endpoint | default "" | quote }}
- name: STORAGE_S3_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: abenix-secrets
      key: STORAGE_S3_ACCESS_KEY
      optional: true
- name: STORAGE_S3_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: abenix-secrets
      key: STORAGE_S3_SECRET_KEY
      optional: true
{{- else if eq $target "azure" -}}
- name: BACKUP_STORE
  value: azure
- name: BACKUP_AZURE_CONTAINER
  value: {{ (.Values.backup.target).azureContainer | default "abenix-backups" | quote }}
- name: STORAGE_AZURE_CONNECTION_STRING
  valueFrom:
    secretKeyRef:
      name: abenix-secrets
      key: STORAGE_AZURE_CONNECTION_STRING
{{- else -}}
- name: BACKUP_STORE
  value: dir
- name: BACKUP_DIR
  value: /backup-target
{{- end -}}
{{- end -}}

{{/* With no object store, backups land on the backup volume */}}
{{- define "abenix.backup.targetMount" -}}
{{- $target := include "abenix.backup.target" . -}}
{{- if not (or (eq $target "s3") (eq $target "azure")) -}}
- name: backup-target
  mountPath: /backup-target
{{- end -}}
{{- end -}}

{{- define "abenix.backup.targetVolume" -}}
{{- $target := include "abenix.backup.target" . -}}
{{- if not (or (eq $target "s3") (eq $target "azure")) -}}
- name: backup-target
  persistentVolumeClaim:
    claimName: {{ include "abenix.fullname" . }}-backup
{{- end -}}
{{- end -}}
