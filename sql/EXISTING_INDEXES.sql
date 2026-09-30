SELECT
    i.index_name,
    i.index_type,
    i.uniqueness,
    c.column_name,
    c.column_position,
    i.status
FROM
    dba_indexes i,
    dba_ind_columns c
WHERE
    i.table_owner = :owner
    AND i.table_name = :table_name
    AND i.index_name = c.index_name
    AND i.owner = c.index_owner
ORDER BY
    i.index_name, c.column_position
