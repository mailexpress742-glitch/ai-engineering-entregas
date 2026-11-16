# Guía de Despliegue de Servicios

Versión 4.0 · Responsable: equipo de Plataforma · Última revisión: febrero de 2026

## 1. Principios

Nubra Cloud despliega a producción varias veces por día. Para que eso sea seguro, todo cambio pasa por el mismo camino automatizado y ningún despliegue se hace a mano. Los despliegues se realizan con GitHub Actions y se ejecutan sobre Kubernetes.

## 2. El pipeline paso a paso

1. **Pull request:** todo cambio entra por un pull request con al menos una aprobación de otra persona del equipo. Los cambios que tocan facturación o autenticación requieren dos aprobaciones.
2. **Integración continua:** se ejecutan las pruebas unitarias, el análisis estático y el escaneo de dependencias vulnerables. Si el escaneo detecta una vulnerabilidad crítica, el pipeline se detiene.
3. **Construcción:** se genera una imagen de contenedor etiquetada con el hash del commit. Nunca se usa la etiqueta `latest`.
4. **Entorno de staging:** el despliegue a staging es automático al fusionar el pull request. Allí se ejecutan las pruebas de integración y una prueba de humo.
5. **Producción:** el despliegue a producción es un botón manual en la herramienta de despliegues, disponible solo después de que staging esté en verde.

## 3. Estrategia de lanzamiento canario

Los despliegues a producción usan un lanzamiento canario en etapas: primero el 5 % del tráfico, luego 25 % y finalmente 100 %. Cada etapa dura al menos 10 minutos. Si la tasa de errores del canario supera el 1 % o la latencia p95 aumenta más de un 20 % respecto de la versión estable, el sistema revierte automáticamente al estado anterior sin intervención humana.

## 4. Ventanas de despliegue

Los despliegues se permiten de lunes a jueves entre las 09:00 y las 17:00, hora de Buenos Aires. Los viernes y vísperas de feriado hay congelamiento de cambios: solo se despliegan correcciones urgentes, con aprobación de la jefatura de Ingeniería. Durante la última semana de cada trimestre fiscal rige un congelamiento total para los servicios de facturación.

## 5. Reversión (rollback)

Cualquier integrante del equipo puede revertir un despliegue desde la herramienta de despliegues con el botón "Revertir a la versión anterior". La reversión tarda alrededor de 3 minutos. Se prefiere siempre revertir primero y analizar después. Si el despliegue incluía una migración de base de datos, esta debe ser compatible hacia atrás: las migraciones destructivas, como eliminar una columna, se hacen en dos despliegues separados.

## 6. Configuración y secretos

La configuración de cada entorno vive en el repositorio de infraestructura. Los secretos (contraseñas, tokens, claves de API) nunca se guardan en el código ni en variables de entorno del pipeline en texto plano: se almacenan en el gestor de secretos y se montan en tiempo de ejecución. Los secretos se rotan cada 90 días o inmediatamente si se sospecha una filtración.

## 7. Observabilidad posterior al despliegue

Después de cada despliegue, la persona responsable debe revisar durante 30 minutos el tablero del servicio: tasa de errores, latencia y saturación de recursos. Cada servicio debe exponer un punto de salud en la ruta `/salud` que devuelva el estado de sus dependencias.
