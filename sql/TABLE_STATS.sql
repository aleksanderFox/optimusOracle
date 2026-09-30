SELECT
    num_rows,
    blocks,
    empty_blocks,
    avg_space,
    chain_cnt,
    avg_row_len,
    last_analyzed
FROM
    dba_tables
WHERE
    owner = :owner
    AND table_name = :table_name
