
//
CREATE EXTERNAL TABLE ticketsdb.tickets_clasificados (
  ticket_id string,
  fecha_creada string,
  canal string,
  mensaje_usuario string,
  prioridad string
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
  'separatorChar' = ',',
  'quoteChar' = '"',
  'escapeChar' = '\\'
)
STORED AS TEXTFILE
LOCATION 's3://tickets-curated-grupo5/curated/'
TBLPROPERTIES (
  'skip.header.line.count'='1'
);


// 
SELECT *
FROM ticketsdb.tickets_clasificados;


//
SELECT prioridad, COUNT(*) AS cantidad
FROM ticketsdb.tickets_clasificados
GROUP BY prioridad;
