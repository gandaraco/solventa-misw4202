-- Usuario de SOLO LECTURA para el arnes (casos PERS-01..03, criterio C2).
-- La tabla la crea MS Pagos al arrancar; los privilegios por defecto hacen que
-- el arnes pueda leerla aunque aun no exista cuando corre este script.
-- Clave de desarrollo: en el entorno real la define Donaldo, no se versiona.
CREATE ROLE harness_lectura LOGIN PASSWORD 'harness_lectura_dev';
GRANT CONNECT ON DATABASE pagos TO harness_lectura;
GRANT USAGE ON SCHEMA public TO harness_lectura;
ALTER DEFAULT PRIVILEGES FOR ROLE pagos IN SCHEMA public GRANT SELECT ON TABLES TO harness_lectura;
