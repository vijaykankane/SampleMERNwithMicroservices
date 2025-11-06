{{- define "backend.name" -}}
{{- default .Chart.Name .Values.nameOverride }}
{{- end -}}

{{- define "backend.fullname" -}}
{{ .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end -}}
