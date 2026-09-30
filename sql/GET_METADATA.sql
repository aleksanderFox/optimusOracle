DECLARE
    v_owner VARCHAR2(30) := :owner;
    v_table VARCHAR2(30) := :table_name;
    v_ddl   CLOB;
BEGIN
    -- Set metadata transform options
    DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'PRETTY',            TRUE);
    DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'SQLTERMINATOR',     TRUE);
    DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'SEGMENT_ATTRIBUTES',TRUE);
    DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'STORAGE',           TRUE);
    DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'TABLESPACE',        FALSE);
    DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'CONSTRAINTS',       TRUE);
    DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'REF_CONSTRAINTS',   TRUE);
    DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'CONSTRAINTS_AS_ALTER',TRUE);

    -- Get table DDL
    v_ddl := DBMS_METADATA.GET_DDL('TABLE', v_table, v_owner);
    DBMS_OUTPUT.PUT_LINE(v_ddl);

    -- Get indexes, constraints, triggers, etc.
    FOR rec IN (
        SELECT object_type, object_name
        FROM   all_objects
        WHERE  owner = v_owner
          AND  object_type IN ('INDEX','TRIGGER','CONSTRAINT')
          AND  object_name IN (
                 SELECT index_name FROM all_indexes
                 WHERE table_owner = v_owner AND table_name = v_table
                 UNION
                 SELECT constraint_name FROM all_constraints
                 WHERE owner = v_owner AND table_name = v_table
                 UNION
                 SELECT trigger_name FROM all_triggers
                 WHERE table_owner = v_owner AND table_name = v_table
               )
    ) LOOP
        BEGIN
            v_ddl := DBMS_METADATA.GET_DDL(rec.object_type, rec.object_name, v_owner);
            DBMS_OUTPUT.PUT_LINE(v_ddl);
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END LOOP;

    -- Comments
    FOR c IN (
        SELECT column_name, comments FROM all_col_comments
        WHERE owner = v_owner AND table_name = v_table AND comments IS NOT NULL
    ) 
    LOOP
        DBMS_OUTPUT.PUT_LINE('COMMENT ON COLUMN ' || v_owner || '.' || v_table || '.' ||c.column_name || ' IS ''' || REPLACE(c.comments,'''','''''') || ''';');
    END LOOP;
END;
