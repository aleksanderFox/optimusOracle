SELECT
    segment_name,
    segment_type,
    ROUND(SUM(bytes) / 1024 / 1024, 2) AS size_mb,
    tablespace_name
FROM
    dba_segments
WHERE
    segment_name = :obj_name
    AND owner = :owner
GROUP BY
    segment_name, segment_type, tablespace_name
