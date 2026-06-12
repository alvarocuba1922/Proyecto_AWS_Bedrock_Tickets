
--crear la tabla
  CREATE EXTERNAL TABLE ticketsdb.tickets_clasificados (
  ticket_id string,
  fecha_creada string,
  canal string,
  mensaje_usuario string,
  prioridad string
)
  
--para llamar todos los registro en la tabla
SELECT *
FROM ticketsdb.tickets_clasificados

--para llamar por fecha
SELECT *
FROM ticketsdb.tickets_clasificados
WHERE fecha_creada = '8/06/2026';

--EL TOTAL
SELECT prioridad, COUNT(*) AS cantidad
FROM ticketsdb.tickets_clasificados
GROUP BY prioridad
ORDER BY cantidad DESC;

--TOTAL POR FECHAS 
SELECT fecha_creada,
       COUNT(*) AS total_tickets
FROM ticketsdb.tickets_clasificados
GROUP BY fecha_creada
ORDER BY fecha_creada;



