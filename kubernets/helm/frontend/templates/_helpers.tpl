{{- define "frontend.name" -}}
{{- default .Chart.Name .Values.nameOverride }}
{{- end -}}

{{- define "frontend.fullname" -}}
{{ .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end -}}

