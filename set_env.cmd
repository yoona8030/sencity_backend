@echo off
cd /d C:\Users\a9349\sencity_backend
call venv311\Scripts\activate
set TF_ENABLE_ONEDNN_OPTS=0
set CLASSIFIER_PRED_FN=external.classification_model.model_test.classify_image
set CLASSIFIER_DRYRUN=
cmd
