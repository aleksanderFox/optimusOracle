SELECT
    o.owner,
    o.object_name,
    o.object_type,
    o.data_object_id
FROM
    dba_hist_sql_plan p,
    dba_objects o
WHERE
    p.sql_id = :sql_id
    AND p.object_owner = o.owner(+)
    AND p.object_name = o.object_name(+)
    AND p.object_type IS NOT NULL
    AND p.object_owner IS NOT NULL
GROUP BY
    o.owner, o.object_name, o.object_type, o.data_object_id
