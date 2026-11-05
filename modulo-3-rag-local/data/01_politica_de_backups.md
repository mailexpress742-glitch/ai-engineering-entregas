# Política de Backups de Nubra Cloud

Versión 3.2 · Responsable: equipo de Infraestructura · Última revisión: marzo de 2026

## 1. Objetivo

Esta política define cómo Nubra Cloud protege los datos de sus clientes y los datos internos frente a pérdida, corrupción o eliminación accidental. Aplica a todas las bases de datos de producción, a los volúmenes de almacenamiento de objetos y a los repositorios de código.

## 2. Frecuencia de los backups

Las bases de datos PostgreSQL de producción se respaldan de tres formas complementarias:

- **Snapshots completos:** una vez por día, a las 02:00 UTC, con una duración habitual de entre 20 y 35 minutos.
- **Archivado continuo de WAL:** los registros de escritura anticipada se envían de forma continua al almacenamiento de respaldo, lo que permite restaurar la base a cualquier punto de los últimos 14 días (recuperación a un punto en el tiempo, o PITR).
- **Copia semanal fuera de línea:** cada domingo se genera una copia cifrada que se guarda en una cuenta de almacenamiento separada, sin credenciales compartidas con producción.

Los volúmenes de almacenamiento de objetos usan versionado: cada versión previa de un archivo se conserva durante 30 días antes de eliminarse definitivamente.

Los repositorios de código se replican cada hora hacia un espacio de respaldo independiente del proveedor principal.

## 3. Retención

| Tipo de backup | Retención |
| --- | --- |
| Snapshot diario | 35 días |
| Copia semanal fuera de línea | 12 semanas |
| Archivo mensual (primer domingo del mes) | 13 meses |
| WAL para PITR | 14 días |

Pasados esos plazos, los backups se eliminan automáticamente con un proceso auditado. Ninguna persona puede borrar backups manualmente sin la aprobación de dos integrantes del equipo de Infraestructura.

## 4. Objetivos de recuperación

Nubra Cloud se compromete con los siguientes objetivos para los servicios críticos:

- **RPO (pérdida máxima de datos aceptable):** 5 minutos, gracias al archivado continuo de WAL.
- **RTO (tiempo máximo para restaurar el servicio):** 2 horas para las bases de datos de producción y 8 horas para el entorno completo.

Los servicios no críticos, como el sitio de documentación o el entorno de demostración, tienen un RTO de 24 horas y un RPO de 24 horas.

## 5. Cifrado y acceso

Todos los backups se cifran en reposo con AES-256. Las claves se gestionan en un servicio de claves dedicado y se rotan cada 90 días. El acceso a los backups está restringido al equipo de Infraestructura y requiere autenticación multifactor. Cada restauración queda registrada con el nombre de quien la solicitó, el motivo y la hora.

## 6. Pruebas de restauración

Un backup que nunca se restaura no es un backup confiable. Por eso, el primer jueves de cada mes el equipo de Infraestructura restaura un snapshot aleatorio en un entorno aislado y valida la integridad de los datos con una suma de comprobación y un conjunto de consultas de control. El resultado se publica en el canal interno #infra-restauraciones. Si una prueba falla, se abre un incidente de severidad 2 de inmediato, según el procedimiento de respuesta a incidentes.

Una vez por año se realiza un simulacro completo de recuperación ante desastres, en el que se reconstruye todo el entorno de producción en una región distinta.

## 7. Qué no cubre esta política

Esta política no cubre los dispositivos personales de los empleados ni los datos guardados en servicios de terceros contratados por los clientes. Los clientes son responsables de sus propios respaldos de esos datos.
