# Pseudocode Function Utama Module Repository

Dokumen ini berisi pseudocode untuk function utama/public pada module `repository`. Function private/helper yang diawali `_` tidak dicantumkan sebagai section utama.

<style>
.pseudocode {
  font-family: Consolas, monospace;
  font-size: 9pt;
  white-space: pre-wrap;
}
</style>

## `repository/schedulerRepository.py`

### `SchedulerRepository.get_config()`

<div class="pseudocode">
GET_CONFIG()

    QUERY <- SELECT SCHEDULER_CONFIG ORDER BY CREATED_AT LIMIT 1

    CONFIG <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN CONFIG
</div>

### `SchedulerRepository.update_config(updates)`

<div class="pseudocode">
UPDATE_CONFIG(UPDATES)

    CONFIG <- CALL SCHEDULER_REPOSITORY.GET_CONFIG()

    FOR EACH FIELD, VALUE IN UPDATES

        SET CONFIG.FIELD <- VALUE

    SET CONFIG.UPDATED_AT <- CURRENT_TIME

    CALL DB.COMMIT()

    CALL DB.REFRESH(CONFIG)

    RETURN CONFIG
</div>

### `SchedulerRepository.update_run_times(last_run_at, next_run_at)`

<div class="pseudocode">
UPDATE_RUN_TIMES(LAST_RUN_AT, NEXT_RUN_AT)

    CONFIG <- CALL SCHEDULER_REPOSITORY.GET_CONFIG()

    SET CONFIG.LAST_RUN_AT <- LAST_RUN_AT

    SET CONFIG.NEXT_RUN_AT <- NEXT_RUN_AT

    SET CONFIG.UPDATED_AT <- CURRENT_TIME

    CALL DB.COMMIT()

    RETURN CONFIG
</div>

## `repository/userRepository.py`

### `UserRepository.create_user(user)`

<div class="pseudocode">
CREATE_USER(USER)

    CALL DB.ADD(USER)

    CALL DB.COMMIT()

    CALL DB.REFRESH(USER)

    RETURN USER
</div>

### `UserRepository.get_by_id(user_id)`

<div class="pseudocode">
GET_BY_ID(USER_ID)

    QUERY <- SELECT USER WHERE USER.ID == USER_ID

    USER <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN USER
</div>

### `UserRepository.get_by_username_or_email(identifier)`

<div class="pseudocode">
GET_BY_USERNAME_OR_EMAIL(IDENTIFIER)

    QUERY <- SELECT USER WHERE USER.USERNAME == IDENTIFIER OR USER.EMAIL == IDENTIFIER

    USER <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN USER
</div>

### `UserRepository.get_by_username(username)`

<div class="pseudocode">
GET_BY_USERNAME(USERNAME)

    QUERY <- SELECT USER WHERE USER.USERNAME == USERNAME

    USER <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN USER
</div>

### `UserRepository.get_all_users(page, limit, search, role, status)`

<div class="pseudocode">
GET_ALL_USERS(PAGE, LIMIT, SEARCH, ROLE, STATUS)

    OFFSET <- (PAGE - 1) * LIMIT

    QUERY <- SELECT USER

    IF SEARCH IS NOT EMPTY

        ADD SEARCH FILTER TO QUERY

    IF ROLE IS NOT EMPTY

        ADD ROLE FILTER TO QUERY

    IF STATUS IS NOT EMPTY

        ADD STATUS FILTER TO QUERY

    ADD ORDER, OFFSET, AND LIMIT TO QUERY

    USERS <- CALL DB.EXECUTE_SCALARS(QUERY)

    RETURN USERS
</div>

### `UserRepository.count_all_users(search, role, status)`

<div class="pseudocode">
COUNT_ALL_USERS(SEARCH, ROLE, STATUS)

    QUERY <- SELECT COUNT(USER.ID)

    IF SEARCH IS NOT EMPTY

        ADD SEARCH FILTER TO QUERY

    IF ROLE IS NOT EMPTY

        ADD ROLE FILTER TO QUERY

    IF STATUS IS NOT EMPTY

        ADD STATUS FILTER TO QUERY

    TOTAL <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN TOTAL
</div>

### `UserRepository.save(user)`

<div class="pseudocode">
SAVE(USER)

    CALL DB.ADD(USER)

    CALL DB.COMMIT()

    CALL DB.REFRESH(USER)

    RETURN USER
</div>

### `UserRepository.delete_user(user)`

<div class="pseudocode">
DELETE_USER(USER)

    CALL DB.DELETE(USER)

    CALL DB.COMMIT()

    RETURN VOID
</div>

### `UserRepository.username_exists(username)`

<div class="pseudocode">
USERNAME_EXISTS(USERNAME)

    QUERY <- SELECT USER.ID WHERE USER.USERNAME == USERNAME

    RESULT <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN RESULT EXISTS
</div>

### `UserRepository.email_exists(email)`

<div class="pseudocode">
EMAIL_EXISTS(EMAIL)

    QUERY <- SELECT USER.ID WHERE USER.EMAIL == EMAIL

    RESULT <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN RESULT EXISTS
</div>

### `UserRepository.revoke_token(token, user_id)`

<div class="pseudocode">
REVOKE_TOKEN(TOKEN, USER_ID)

    EXISTING <- CALL USER_REPOSITORY.IS_TOKEN_REVOKED(TOKEN)

    IF EXISTING IS TRUE

        RETURN VOID

    REVOKED_TOKEN <- CREATE_REVOKED_TOKEN(TOKEN, USER_ID)

    CALL DB.ADD(REVOKED_TOKEN)

    CALL DB.COMMIT()

    RETURN VOID
</div>

### `UserRepository.is_token_revoked(token)`

<div class="pseudocode">
IS_TOKEN_REVOKED(TOKEN)

    QUERY <- SELECT REVOKED_TOKEN WHERE TOKEN == TOKEN

    RESULT <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN RESULT EXISTS
</div>

### `UserRepository.get_active_reset_pin(user_id)`

<div class="pseudocode">
GET_ACTIVE_RESET_PIN(USER_ID)

    QUERY <- SELECT PASSWORD_RESET_PIN WHERE USER_ID == USER_ID AND USED == FALSE AND EXPIRES_AT > CURRENT_TIME

    RECORD <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN RECORD
</div>

### `UserRepository.create_reset_pin(record)`

<div class="pseudocode">
CREATE_RESET_PIN(RECORD)

    DELETE_QUERY <- DELETE PASSWORD_RESET_PIN WHERE USER_ID == RECORD.USER_ID AND USED == FALSE

    CALL DB.EXECUTE(DELETE_QUERY)

    CALL DB.ADD(RECORD)

    CALL DB.COMMIT()

    CALL DB.REFRESH(RECORD)

    RETURN RECORD
</div>

### `UserRepository.mark_reset_pin_used(record)`

<div class="pseudocode">
MARK_RESET_PIN_USED(RECORD)

    SET RECORD.USED <- TRUE

    SET RECORD.USED_AT <- CURRENT_TIME

    CALL DB.COMMIT()

    RETURN RECORD
</div>

`

### `ChatQueryRepository.execute_read_query(sql)`

<div class="pseudocode">
EXECUTE_READ_QUERY(SQL)

    RESULT <- CALL DB.EXECUTE_TEXT(SQL)

    ROWS <- CALL RESULT.MAPPINGS_ALL()

    COUNT <- LENGTH(ROWS)

    RETURN ROWS, COUNT
</div>

## `repository/kpiMasterRepository.py`

### `KPIMasterRepository.upsert_by_group(records)`

<div class="pseudocode">
UPSERT_BY_GROUP(RECORDS)

    INGESTED_COUNT <- 0

    FAILED_COUNT <- 0

    FOR EACH RECORD IN RECORDS

        EXISTING <- SELECT KPI_MASTER WHERE GROUP_ID == RECORD.GROUP_ID AND KPI_NAME == RECORD.KPI_NAME

        IF EXISTING EXISTS

            UPDATE EXISTING WITH RECORD VALUES

        ELSE

            NEW_RECORD <- CREATE KPI_MASTER FROM RECORD

            CALL DB.ADD(NEW_RECORD)

        CALL KPI_MASTER_REPOSITORY.SYNC_PIC_USERS(RECORD)

        INCREMENT INGESTED_COUNT

    CALL DB.COMMIT()

    RETURN SUMMARY(INGESTED_COUNT, FAILED_COUNT)
</div>

### `KPIMasterRepository.get_id_map_by_names(kpi_names, tahun)`

<div class="pseudocode">
GET_ID_MAP_BY_NAMES(KPI_NAMES, TAHUN)

    QUERY <- SELECT KPI_MASTER.ID, KPI_MASTER.KPI_NAME WHERE KPI_NAME IN KPI_NAMES AND TAHUN == TAHUN

    ROWS <- CALL DB.EXECUTE(QUERY)

    ID_MAP <- MAP KPI_NAME TO ID FROM ROWS

    RETURN ID_MAP
</div>

### `KPIMasterRepository.delete_by_group_id(group_id)`

<div class="pseudocode">
DELETE_BY_GROUP_ID(GROUP_ID)

    QUERY <- DELETE KPI_MASTER WHERE GROUP_ID == GROUP_ID

    CALL DB.EXECUTE(QUERY)

    CALL DB.COMMIT()

    RETURN VOID
</div>



### `AuditLogRepository.create(data)`

<div class="pseudocode">
CREATE(DATA)

    LOG <- CREATE CHATBOT_AUDIT_LOG FROM DATA

    CALL DB.ADD(LOG)

    CALL DB.COMMIT()

    CALL DB.REFRESH(LOG)

    RETURN LOG
</div>

### `AuditLogRepository.get_by_user(user_id, skip, limit)`

<div class="pseudocode">
GET_BY_USER(USER_ID, SKIP, LIMIT)

    QUERY <- SELECT AUDIT_LOG WHERE USER_ID == USER_ID ORDER BY CREATED_AT DESC OFFSET SKIP LIMIT LIMIT

    LOGS <- CALL DB.EXECUTE_SCALARS(QUERY)

    RETURN LOGS
</div>

### `AuditLogRepository.get_by_session(session_id)`

<div class="pseudocode">
GET_BY_SESSION(SESSION_ID)

    QUERY <- SELECT AUDIT_LOG WHERE SESSION_ID == SESSION_ID ORDER BY CREATED_AT ASC

    LOGS <- CALL DB.EXECUTE_SCALARS(QUERY)

    RETURN LOGS
</div>

### `AuditLogRepository.get_failed_wireguard(skip, limit)`

<div class="pseudocode">
GET_FAILED_WIREGUARD(SKIP, LIMIT)

    QUERY <- SELECT AUDIT_LOG WHERE WIREGUARD_STATUS == FAILED ORDER BY CREATED_AT DESC OFFSET SKIP LIMIT LIMIT

    LOGS <- CALL DB.EXECUTE_SCALARS(QUERY)

    RETURN LOGS
</div>

### `AuditLogRepository.get_by_id(log_id)`

<div class="pseudocode">
GET_BY_ID(LOG_ID)

    QUERY <- SELECT AUDIT_LOG WHERE ID == LOG_ID

    LOG <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN LOG
</div>

### `AuditLogRepository.delete_by_session(session_id)`

<div class="pseudocode">
DELETE_BY_SESSION(SESSION_ID)

    QUERY <- DELETE AUDIT_LOG WHERE SESSION_ID == SESSION_ID

    CALL DB.EXECUTE(QUERY)

    CALL DB.COMMIT()

    RETURN VOID
</div>



### `ClarificationRepository.create(session_id, user_id, ...)`

<div class="pseudocode">
CREATE(SESSION_ID, USER_ID, QUERY, QUESTION, AMBIGUITY)

    LOG <- CREATE CLARIFICATION_LOG(SESSION_ID, USER_ID, QUERY, QUESTION, AMBIGUITY)

    CALL DB.ADD(LOG)

    CALL DB.COMMIT()

    CALL DB.REFRESH(LOG)

    RETURN LOG
</div>

### `ClarificationRepository.update_with_answer(log_id, answer, disambiguated_query)`

<div class="pseudocode">
UPDATE_WITH_ANSWER(LOG_ID, ANSWER, DISAMBIGUATED_QUERY)

    LOG <- CALL CLARIFICATION_REPOSITORY.GET_BY_ID(LOG_ID)

    SET LOG.ANSWER <- ANSWER

    SET LOG.DISAMBIGUATED_QUERY <- DISAMBIGUATED_QUERY

    SET LOG.ANSWERED_AT <- CURRENT_TIME

    CALL DB.COMMIT()

    CALL DB.REFRESH(LOG)

    RETURN LOG
</div>

### `ClarificationRepository.update_feedback(log_id, user_feedback, needed_correction)`

<div class="pseudocode">
UPDATE_FEEDBACK(LOG_ID, USER_FEEDBACK, NEEDED_CORRECTION)

    LOG <- CALL CLARIFICATION_REPOSITORY.GET_BY_ID(LOG_ID)

    SET LOG.USER_FEEDBACK <- USER_FEEDBACK

    SET LOG.NEEDED_CORRECTION <- NEEDED_CORRECTION

    CALL DB.COMMIT()

    RETURN LOG
</div>

### `ClarificationRepository.get_by_session(session_id)`

<div class="pseudocode">
GET_BY_SESSION(SESSION_ID)

    QUERY <- SELECT CLARIFICATION_LOG WHERE SESSION_ID == SESSION_ID ORDER BY CREATED_AT ASC

    LOGS <- CALL DB.EXECUTE_SCALARS(QUERY)

    RETURN LOGS
</div>

### `ClarificationRepository.get_by_user(user_id, skip, limit)`

<div class="pseudocode">
GET_BY_USER(USER_ID, SKIP, LIMIT)

    QUERY <- SELECT CLARIFICATION_LOG WHERE USER_ID == USER_ID ORDER BY CREATED_AT DESC OFFSET SKIP LIMIT LIMIT

    LOGS <- CALL DB.EXECUTE_SCALARS(QUERY)

    RETURN LOGS
</div>

### `ClarificationRepository.get_clarify_decisions_count(session_id)`

<div class="pseudocode">
GET_CLARIFY_DECISIONS_COUNT(SESSION_ID)

    QUERY <- SELECT COUNT(CLARIFICATION_LOG.ID) WHERE SESSION_ID == SESSION_ID

    COUNT <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN COUNT
</div>

### `ClarificationRepository.get_last_clarification(session_id)`

<div class="pseudocode">
GET_LAST_CLARIFICATION(SESSION_ID)

    QUERY <- SELECT CLARIFICATION_LOG WHERE SESSION_ID == SESSION_ID ORDER BY CREATED_AT DESC LIMIT 1

    LOG <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN LOG
</div>

### `ClarificationRepository.delete_by_session(session_id)`

<div class="pseudocode">
DELETE_BY_SESSION(SESSION_ID)

    QUERY <- DELETE CLARIFICATION_LOG WHERE SESSION_ID == SESSION_ID

    CALL DB.EXECUTE(QUERY)

    CALL DB.COMMIT()

    RETURN VOID
</div>

## `repository/ingestionLogRepository.py`

### `IngestionLogRepository.create(kpi_group_id, source_type, group_name)`

<div class="pseudocode">
CREATE(KPI_GROUP_ID, SOURCE_TYPE, GROUP_NAME)

    LOG <- CREATE INGESTION_LOG(KPI_GROUP_ID, SOURCE_TYPE, GROUP_NAME, STATUS="FAILED")

    CALL DB.ADD(LOG)

    CALL DB.COMMIT()

    CALL DB.REFRESH(LOG)

    RETURN LOG
</div>

### `IngestionLogRepository.update_status(log_id, status, total_rows, ingested_count, failed_count, errors)`

<div class="pseudocode">
UPDATE_STATUS(LOG_ID, STATUS, TOTAL_ROWS, INGESTED_COUNT, FAILED_COUNT, ERRORS)

    LOG <- SELECT INGESTION_LOG WHERE ID == LOG_ID

    SET LOG.STATUS <- STATUS

    SET LOG.TOTAL_ROWS <- TOTAL_ROWS

    SET LOG.INGESTED_COUNT <- INGESTED_COUNT

    SET LOG.FAILED_COUNT <- FAILED_COUNT

    SET LOG.ERRORS <- ERRORS

    SET LOG.FINISHED_AT <- CURRENT_TIME

    CALL DB.COMMIT()

    RETURN LOG
</div>

### `IngestionLogRepository.list_with_group(offset, limit, source_type, status, start_datetime, end_datetime)`

<div class="pseudocode">
LIST_WITH_GROUP(OFFSET, LIMIT, SOURCE_TYPE, STATUS, START_DATETIME, END_DATETIME)

    QUERY <- SELECT INGESTION_LOG JOIN KPI_GROUP

    IF SOURCE_TYPE IS NOT EMPTY

        ADD SOURCE_TYPE FILTER TO QUERY

    IF STATUS IS NOT EMPTY

        ADD STATUS FILTER TO QUERY

    IF START_DATETIME IS NOT EMPTY

        ADD START_DATE FILTER TO QUERY

    IF END_DATETIME IS NOT EMPTY

        ADD END_DATE FILTER TO QUERY

    TOTAL <- CALL DB.EXECUTE_COUNT(QUERY)

    LOGS <- CALL DB.EXECUTE_SCALARS(QUERY ORDER BY CREATED_AT DESC OFFSET OFFSET LIMIT LIMIT)

    RETURN LOGS, TOTAL
</div>

### `IngestionLogRepository.get_by_group(kpi_group_id, limit)`

<div class="pseudocode">
GET_BY_GROUP(KPI_GROUP_ID, LIMIT)

    QUERY <- SELECT INGESTION_LOG WHERE KPI_GROUP_ID == KPI_GROUP_ID ORDER BY CREATED_AT DESC LIMIT LIMIT

    LOGS <- CALL DB.EXECUTE_SCALARS(QUERY)

    RETURN LOGS
</div>

## `repository/KpiGroupRepository.py`

### `KPIGroupRepository.get_active_scheduled_tracker()`

<div class="pseudocode">
GET_ACTIVE_SCHEDULED_TRACKER()

    QUERY <- SELECT KPI_GROUP WHERE GROUP_TYPE == TRACKER AND IS_ACTIVE == TRUE

    GROUPS <- CALL DB.EXECUTE_SCALARS(QUERY)

    RETURN GROUPS
</div>

### `KPIGroupRepository.get_or_create(sheet_id, group_type, ...)`

<div class="pseudocode">
GET_OR_CREATE(SHEET_ID, GROUP_TYPE, METADATA)

    GROUP <- SELECT KPI_GROUP WHERE SHEET_ID == SHEET_ID AND GROUP_TYPE == GROUP_TYPE

    IF GROUP EXISTS

        UPDATE GROUP WITH METADATA

    ELSE

        GROUP <- CREATE KPI_GROUP FROM METADATA

        CALL DB.ADD(GROUP)

    CALL DB.FLUSH()

    RETURN GROUP
</div>

### `KPIGroupRepository.get_or_create_committed(...)`

<div class="pseudocode">
GET_OR_CREATE_COMMITTED(METADATA)

    GROUP <- CALL KPI_GROUP_REPOSITORY.GET_OR_CREATE(METADATA)

    CALL DB.COMMIT()

    CALL DB.REFRESH(GROUP)

    RETURN GROUP
</div>

### `KPIGroupRepository.get_by_id(group_id)`

<div class="pseudocode">
GET_BY_ID(GROUP_ID)

    QUERY <- SELECT KPI_GROUP WHERE ID == GROUP_ID WITH CONDITIONAL RECORDS LOAD

    GROUP <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN GROUP
</div>

### `KPIGroupRepository.get_master_groups(page, limit)`

<div class="pseudocode">
GET_MASTER_GROUPS(PAGE, LIMIT)

    OFFSET <- (PAGE - 1) * LIMIT

    QUERY <- SELECT KPI_GROUP WHERE GROUP_TYPE == MASTER ORDER BY CREATED_AT DESC OFFSET OFFSET LIMIT LIMIT

    GROUPS <- CALL DB.EXECUTE_SCALARS(QUERY)

    RETURN GROUPS
</div>

### `KPIGroupRepository.list_groups(page, limit, tahun, group_type, search)`

<div class="pseudocode">
LIST_GROUPS(PAGE, LIMIT, TAHUN, GROUP_TYPE, SEARCH)

    OFFSET <- (PAGE - 1) * LIMIT

    QUERY <- SELECT KPI_GROUP

    IF TAHUN IS NOT EMPTY

        ADD TAHUN FILTER TO QUERY

    IF GROUP_TYPE IS NOT EMPTY

        ADD GROUP_TYPE FILTER TO QUERY

    IF SEARCH IS NOT EMPTY

        ADD SEARCH FILTER TO QUERY

    TOTAL <- CALL DB.EXECUTE_COUNT(QUERY)

    GROUPS <- CALL DB.EXECUTE_SCALARS(QUERY ORDER BY CREATED_AT DESC OFFSET OFFSET LIMIT LIMIT)

    RETURN GROUPS, TOTAL
</div>

### `KPIGroupRepository.update(group_id, fields)`

<div class="pseudocode">
UPDATE(GROUP_ID, FIELDS)

    GROUP <- CALL KPI_GROUP_REPOSITORY.GET_BY_ID(GROUP_ID)

    FOR EACH FIELD, VALUE IN FIELDS

        SET GROUP.FIELD <- VALUE

    CALL DB.FLUSH()

    RETURN GROUP
</div>

### `KPIGroupRepository.update_committed(group_id, fields)`

<div class="pseudocode">
UPDATE_COMMITTED(GROUP_ID, FIELDS)

    GROUP <- CALL KPI_GROUP_REPOSITORY.UPDATE(GROUP_ID, FIELDS)

    CALL DB.COMMIT()

    CALL DB.REFRESH(GROUP)

    RETURN GROUP
</div>

### `KPIGroupRepository.delete(group_id)`

<div class="pseudocode">
DELETE(GROUP_ID)

    GROUP <- CALL KPI_GROUP_REPOSITORY.GET_BY_ID(GROUP_ID)

    CALL DB.DELETE(GROUP)

    CALL DB.FLUSH()

    RETURN GROUP
</div>

### `KPIGroupRepository.delete_committed(group_id)`

<div class="pseudocode">
DELETE_COMMITTED(GROUP_ID)

    GROUP <- CALL KPI_GROUP_REPOSITORY.DELETE(GROUP_ID)

    CALL DB.COMMIT()

    RETURN GROUP
</div>



### `ChatSessionRepository.create(session_id, user_id, title)`

<div class="pseudocode">
CREATE(SESSION_ID, USER_ID, TITLE)

    SESSION <- CREATE CHAT_SESSION(SESSION_ID, USER_ID, TITLE)

    CALL DB.ADD(SESSION)

    CALL DB.COMMIT()

    CALL DB.REFRESH(SESSION)

    RETURN SESSION
</div>

### `ChatSessionRepository.get_by_user(user_id)`

<div class="pseudocode">
GET_BY_USER(USER_ID)

    QUERY <- SELECT CHAT_SESSION WHERE USER_ID == USER_ID ORDER BY UPDATED_AT DESC

    SESSIONS <- CALL DB.EXECUTE_SCALARS(QUERY)

    RETURN SESSIONS
</div>

### `ChatSessionRepository.get_by_id(session_id)`

<div class="pseudocode">
GET_BY_ID(SESSION_ID)

    QUERY <- SELECT CHAT_SESSION WHERE ID == SESSION_ID

    SESSION <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN SESSION
</div>

### `ChatSessionRepository.update_title(session_id, title)`

<div class="pseudocode">
UPDATE_TITLE(SESSION_ID, TITLE)

    SESSION <- CALL CHAT_SESSION_REPOSITORY.GET_BY_ID(SESSION_ID)

    SET SESSION.TITLE <- TITLE

    SET SESSION.UPDATED_AT <- CURRENT_TIME

    CALL DB.COMMIT()

    CALL DB.REFRESH(SESSION)

    RETURN SESSION
</div>

### `ChatSessionRepository.delete(session_id)`

<div class="pseudocode">
DELETE(SESSION_ID)

    SESSION <- CALL CHAT_SESSION_REPOSITORY.GET_BY_ID(SESSION_ID)

    CALL DB.DELETE(SESSION)

    CALL DB.COMMIT()

    RETURN VOID
</div>

## `repository/kpiTrackerRepository.py`

### `KPITrackerRepository.bulk_insert_kpi_records(records)`

<div class="pseudocode">
BULK_INSERT_KPI_RECORDS(RECORDS)

    CLEAN_RECORDS <- REMOVE_NON_DB_FIELDS(RECORDS)

    OBJECTS <- MAP_EACH(CLEAN_RECORDS, KPI_TRACKER_MODEL)

    CALL DB.ADD_ALL(OBJECTS)

    CALL DB.COMMIT()

    RETURN INSERT_SUMMARY(LENGTH(OBJECTS))
</div>

### `KPITrackerRepository.delete_kpi_records_by_group_and_period(group_id, bulan_num)`

<div class="pseudocode">
DELETE_KPI_RECORDS_BY_GROUP_AND_PERIOD(GROUP_ID, BULAN_NUM)

    QUERY <- DELETE KPI_TRACKER WHERE GROUP_ID == GROUP_ID

    IF BULAN_NUM IS NOT EMPTY

        ADD BULAN_NUM FILTER TO QUERY

    RESULT <- CALL DB.EXECUTE(QUERY)

    CALL DB.COMMIT()

    RETURN RESULT.ROWCOUNT
</div>

## `repository/chatbotRepository.py`

### `ChatbotRepository.get_by_id(chatbot_id)`

<div class="pseudocode">
GET_BY_ID(CHATBOT_ID)

    QUERY <- SELECT CHATBOT WHERE ID == CHATBOT_ID

    CHATBOT <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN CHATBOT
</div>

### `ChatbotRepository.get_by_chatbot_name(chatbot_name)`

<div class="pseudocode">
GET_BY_CHATBOT_NAME(CHATBOT_NAME)

    QUERY <- SELECT CHATBOT WHERE LOWER(CHATBOT_NAME) == LOWER(CHATBOT_NAME) AND IS_ACTIVE == TRUE

    CHATBOT <- CALL DB.EXECUTE_SCALAR(QUERY)

    RETURN CHATBOT
</div>

### `ChatbotRepository.get_all(page, limit, authority, search)`

<div class="pseudocode">
GET_ALL(PAGE, LIMIT, AUTHORITY, SEARCH)

    OFFSET <- (PAGE - 1) * LIMIT

    QUERY <- SELECT CHATBOT WHERE IS_ACTIVE == TRUE

    IF AUTHORITY IS NOT EMPTY

        ADD AUTHORITY FILTER TO QUERY

    IF SEARCH IS NOT EMPTY

        ADD SEARCH FILTER TO QUERY

    TOTAL <- CALL DB.EXECUTE_COUNT(QUERY)

    CHATBOTS <- CALL DB.EXECUTE_SCALARS(QUERY ORDER BY CREATED_AT DESC OFFSET OFFSET LIMIT LIMIT)

    TOTAL_PAGES <- CEIL(TOTAL / LIMIT)

    RETURN DICTIONARY("DATA", CHATBOTS, "TOTAL", TOTAL, "PAGE", PAGE, "LIMIT", LIMIT, "TOTAL_PAGES", TOTAL_PAGES)
</div>

### `ChatbotRepository.create(payload)`

<div class="pseudocode">
CREATE(PAYLOAD)

    CHATBOT <- CREATE CHATBOT FROM PAYLOAD

    CALL DB.ADD(CHATBOT)

    CALL DB.COMMIT()

    CALL DB.REFRESH(CHATBOT)

    RETURN CHATBOT
</div>

### `ChatbotRepository.deactivate_active_by_authority(authority, exclude_id)`

<div class="pseudocode">
DEACTIVATE_ACTIVE_BY_AUTHORITY(AUTHORITY, EXCLUDE_ID)

    QUERY <- UPDATE CHATBOT SET IS_ACTIVE = FALSE WHERE AUTHORITY == AUTHORITY AND IS_ACTIVE == TRUE

    IF EXCLUDE_ID IS NOT EMPTY

        ADD ID != EXCLUDE_ID FILTER TO QUERY

    CALL DB.EXECUTE(QUERY)

    CALL DB.COMMIT()

    RETURN VOID
</div>

### `ChatbotRepository.update(payload)`

<div class="pseudocode">
UPDATE(PAYLOAD)

    CHATBOT <- CALL CHATBOT_REPOSITORY.GET_BY_ID(PAYLOAD.ID)

    FOR EACH FIELD, VALUE IN PAYLOAD

        IF VALUE IS PROVIDED

            SET CHATBOT.FIELD <- VALUE

    CALL DB.COMMIT()

    CALL DB.REFRESH(CHATBOT)

    RETURN CHATBOT
</div>

### `ChatbotRepository.soft_delete()`

<div class="pseudocode">
SOFT_DELETE(CHATBOT)

    SET CHATBOT.IS_ACTIVE <- FALSE

    CALL DB.COMMIT()

    RETURN CHATBOT
</div>

### `ChatbotRepository.hard_delete()`

<div class="pseudocode">
HARD_DELETE(CHATBOT)

    CALL DB.DELETE(CHATBOT)

    CALL DB.COMMIT()

    RETURN VOID
</div>
