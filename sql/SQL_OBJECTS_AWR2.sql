with objects as
(
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
)
    select
        oi.owner,
        oi.object_name,
        oi.object_type,
        oi.data_object_id
    from
        objects o
        join
            all_indexes i
        on
            i.index_name = o.object_name
            and i.table_owner = o.owner
        join
            dba_objects oi
        on
            oi.object_name = i.table_name
            and oi.OWNER = i.table_owner
    where
        o.OBJECT_TYPE = 'INDEX'
    union
    select
        owner,
        object_name,
        object_type,
        data_object_id
    from
        objects
