pylupdate6 oracle_query_optimizer.py -ts i18n/translation_ru_RU.ts
pyside6-lrelease i18n/translation_ru_RU.ts -qm i18n/translation_ru_RU.qm
if exist i18n/translation_en_US.ts (
    pyside6-lrelease i18n/translation_en_US.ts -qm i18n/translation_en_US.qm   
)