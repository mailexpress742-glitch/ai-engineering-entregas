# Procedimiento de Respuesta a Incidentes

Versión 2.5 · Responsable: equipo de Confiabilidad (SRE) · Última revisión: enero de 2026

## 1. Qué es un incidente

Un incidente es cualquier evento que degrada o interrumpe un servicio de Nubra Cloud, o que pone en riesgo la seguridad de los datos. Todo empleado puede declarar un incidente: ante la duda, se declara.

## 2. Niveles de severidad

| Severidad | Descripción | Tiempo de respuesta | Frecuencia de actualización |
| --- | --- | --- | --- |
| SEV1 | Caída total o pérdida de datos de clientes | 5 minutos | cada 15 minutos |
| SEV2 | Degradación importante o falla de una función crítica | 15 minutos | cada 30 minutos |
| SEV3 | Problema menor con solución alternativa disponible | 4 horas | una vez por día |

Un incidente SEV1 se comunica a la página de estado pública en un máximo de 10 minutos desde su declaración.

## 3. Roles durante un incidente

- **Comandante de incidente (IC):** coordina la respuesta, toma las decisiones y delega tareas. No debe ejecutar cambios técnicos. En un SEV1, el IC es siempre un integrante senior del equipo SRE.
- **Responsable técnico:** investiga y aplica las correcciones.
- **Responsable de comunicaciones:** redacta las actualizaciones para clientes y para la página de estado.
- **Escriba:** registra la línea de tiempo en el canal #incidentes-activos.

En incidentes SEV3 una sola persona puede asumir todos los roles.

## 4. Guardia (on-call)

El equipo SRE mantiene una guardia rotativa semanal, que cambia los lunes a las 10:00 hora de Buenos Aires. Cada turno tiene un titular y un suplente. Las alertas llegan primero al titular; si no las reconoce en 5 minutos, se escalan automáticamente al suplente y, pasados otros 10 minutos, a la jefatura de Ingeniería. La guardia se compensa con un adicional por semana cubierta y un día libre posterior si hubo más de dos activaciones nocturnas.

## 5. Pasos de la respuesta

1. **Detectar y declarar:** abrir el incidente con el comando `/incidente nuevo` en el chat interno, indicando severidad y servicio afectado.
2. **Estabilizar:** priorizar detener el daño (revertir un despliegue, desviar tráfico, activar el modo degradado) antes de buscar la causa raíz.
3. **Comunicar:** informar el estado en los tiempos de la tabla de severidades.
4. **Resolver:** confirmar con métricas que el servicio volvió a la normalidad durante al menos 30 minutos.
5. **Cerrar:** el IC cierra el incidente y agenda el análisis posterior.

## 6. Análisis posterior (postmortem)

Todo incidente SEV1 o SEV2 requiere un postmortem sin culpables, publicado dentro de los 5 días hábiles posteriores al cierre. Debe incluir la línea de tiempo, el impacto medido (minutos de caída y clientes afectados), la causa raíz, qué funcionó, qué no funcionó y acciones correctivas con responsable y fecha. Las acciones correctivas se registran como tareas y se revisan en la reunión mensual de confiabilidad.

## 7. Incidentes de seguridad

Si el incidente involucra acceso no autorizado a datos, se avisa de inmediato al equipo de Seguridad, que asume la dirección técnica. Según la normativa aplicable, la notificación a los clientes afectados debe realizarse dentro de las 72 horas desde que se confirma la brecha.
