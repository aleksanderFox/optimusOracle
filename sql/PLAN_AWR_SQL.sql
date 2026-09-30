SELECT * FROM TABLE(dbms_xplan.display_awr(
    sql_id => :sql_id, 
    plan_hash_value => :plan_hash, 
    format => 'TYPICAL +PREDICATE +ALIAS'
))
