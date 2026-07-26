# Angel's Notes 
> These are my personal notes, here I'll write the reason behind the tecnical desicions of why or how the project was developed, in order to create some sort of documentation for this project as well as a learning note for myself. 

* Remove the idea of creating 2 envs like "dev" and "prod" this was an old idea to show my skills as "devOps" but I want to get more focused in Data Quality and MLOps rather than "Hard Code Cloud DevOps"

## PR-001 — Repo hygiene baseline
* Removed extra files in the "temp_files" that were test done previouly on this project.
* removed duplicated data in gitignore file
* added new virtual environment for python.
* Instead of using a setup.py or setup.cfg we are using now `pyproject.toml`
* added `makefile` in order to make things easier when deploying the architecture in a new pc or in local.
* Added `.pre-commit-cofing.yaml` file in order to check the quality of the code in terraform, python and jupyterNotebooks before sending it to the repo.
* Installed and enabled the command `gh` for "Git Hub CLI" so commands can be ran easly from the local terminal. 

## PR-002 - Inventory and protect prod buckets (no Terraform yet)
* The 2 json files in `/scripts/policies` are the bucket rules for protect the S3 buckets where the data is storage. 
* The `.txt` files in `/docs/inventory` are snapshots of current status in AWS about the data extracted with a readme file that explains why they exist. 
* Also, created a "safety belt" prior any refactor the file `scripts/00_inventory_and_protect.sh` 
    * Colors: allows the output termnal to show different colors based on "fail", "success" or any oter scenario when doing the dry run
    * Preconditions: verifies if the AWS profile, region and AWS command exists prior doing any change. 
    * Per-bucket work: creates and inventory of items in the buckets, enables the versioning on both buckets, adds the "deny policy" on both buckets.
    * Deny Delte Rule applies to all the users except for the __Admin__ in the AWS account. 
    * This was wrote in `.sh` file because these are pre-existing buckets, so __Terraform__ is not very good handling existing items, that's why the changes were done using __Bash__ and __AWS__.

## PR-003 - Move existing TF state to remote backend (no resource changes)
On this PR the "refactor" is the pre-step move the terraform state file to a remote backend is done. 
* Created the `bootstrap/terrraform` directories in order to create the .tf files 
* dyamodb.tf, main.tf, and so on were created in order to set a S3 bucket in AWS and DynamoDB for blocking stated (as a real life production project)
* The local (as per now) is not scalable and just "toy project" like. HashiCorp's Cloud could be used but still we depend on "someone else's" service, so is a better idea to centralize everything in AWS with all the protection rules for that bucket and blcoking the state file with dynamoDB with a ver low cost. 

## PR-004 Move existing TF state to remote backend (no resource changes)
Because I moved from Guatemala city to Montevideo Uruguay, the computer where the project used to lived was formatter and left in Guatemala. 
So there is no `terraform.tfstate` (the exact same reason why I was planning to move to S3) so there is no way to do a migration to AWS because there is nothing to migrate. 
Now the plan changed, I need to do an import of all the resources in AWS. The infrastructure is still there in AWS working as usual, but I need to do the import and rebuild the `terraform.tfstate` file.  
While doing the import and finding what is missing 5 blocks were unabled to be imported: 

* null_resource.run_glue_crawlers
* null_resource.run_silver_glue_crawlers
* aws_iam_policy_attachment.glue_service_policy
* aws_lakeformation_resource.athena_results_location
* aws_sagemaker_user_profile.lottery_user

So this points are going to be worked in the following PR in order to get a full control over them and make them reproduceble through Terraform. 

    - The crawlers, they no longer exist in the current architecture. 
    - `aws_iam_policy_attachment.glue_service_policy` cannot be imported by design, there is no way I can import this from AWS
    - Lakeformation was deployed manually, at the time I was unable to do it through Terraform so I had to do it manually, impossible to import this one
    - Sagemaker: import works, but a provider bug crashes the read-back

After import the resources and comment the "unimportable" resources, the `terraform.tfstate` was rebuiled successfully!

## PR-005 — Import existing buckets into Terraform with `prevent_destroy` 
When I started doing this project I cretaed several buckets manually one of those were `lottery-partitioned-storage-prod` and `lottery-data-simple-prod` one for "Hive-style" data (better to use with Athena and SQL queries) and the other one for "Simple checks" better for run notebooks and do manual verificationa about the extracted data of each weekly lottery. 
The problem is that originally I didn't import them so I left the terraform code commented just to remember myself about that "buckets exist but were not created in here". 

Now they were officially imported to the terraform code and are managed by Terraform and will "live" in the S3 remote backend. Also, for consistency the were renamed in the terraform code to:

| | Terraform label (the address in HCL) | Real AWS bucket name (`bucket = "..."`) |
|---|---|---|
| **Before** | `aws_s3_bucket.lottery_raw_data` | `lottery-partitioned-storage-prod` |
| **After** | `aws_s3_bucket.lottery_partitioned` | `lottery-partitioned-storage-prod` ← *unchanged* |
| **Before** | `aws_s3_bucket.lottery_data_simple` | `lottery-data-simple-prod` |
| **After** | `aws_s3_bucket.lottery_simple` | `lottery-data-simple-prod` ← *unchanged* |

## PR-006 — Module skeleton + terraform/ `root caller`
The original code structure was very messy, so in order to make it more professional and easy to navigate all the scaffolding has to be changed. 

The way that terraform docs are organized doesn't affect the real infraestructure however, I have to be very carefull when moving the resources because if I only move one file to a new place and then I do `Terraform Apply` terraform will think that is a new resources and will destroy the original and create a new one identical (but empty if that is an S3 bucket). 

For that I have to use the `terraform state mv` in order to keep the `terraform plan` empty and avoid a disaster when moving the resources to the new place. 

## PR-007 — Migrate storage module (the imported buckets)

Because the terraform.tfstate was deleted and now we are creating a brand new state file in S3 (Remote State File) and we are reorganizing the code infrastructure to something more "professional" and easy to read some steps needs to be taken: 

1. Create the new infrastructure for the terraform code.
2. Move the legacy code from the `S3.tf` file to the new `terraform/modules/storage/` directories 
3. the command `terraform state mv` does not work here because I don't have the legacy state file so is needed for first import the bucket resources to the new terraform code like so: 
```bash
cd terraform/

terraform import module.storage.aws_s3_bucket.lottery_partitioned                              lottery-partitioned-storage-prod
terraform import module.storage.aws_s3_bucket_versioning.lottery_partitioned                   lottery-partitioned-storage-prod
terraform import module.storage.aws_s3_bucket_server_side_encryption_configuration.lottery_partitioned lottery-partitioned-storage-prod
terraform import module.storage.aws_s3_bucket_public_access_block.lottery_partitioned          lottery-partitioned-storage-prod
```
4. After the import removed or "make forget" the pointer of terraform from the legacy s3.tf file like so: 
```bash
cd ../terraform-lottery/Prod

terraform state rm \
  aws_s3_bucket.lottery_partitioned \
  aws_s3_bucket_versioning.lottery_partitioned \
  aws_s3_bucket_server_side_encryption_configuration.lottery_partitioned \
  aws_s3_bucket_public_access_block.lottery_partitioned \
  aws_s3_bucket.lottery_simple \
  aws_s3_bucket_versioning.lottery_simple \
  aws_s3_bucket_server_side_encryption_configuration.lottery_simple \
  aws_s3_bucket_public_access_block.lottery_simple \
  aws_s3_bucket.lambda_code_zip \
  aws_s3_bucket.athena_results \
  aws_s3_bucket_public_access_block.athena_results \
  aws_s3_bucket_server_side_encryption_configuration.athena_results \
  aws_s3_bucket_lifecycle_configuration.athena_results
```

After making sure that `terraform plan` does not alerts of any change when located in `terraform/` directory, and `cd ../terraform-lottery/Prod` `terraform plan` shows that there are no changes and infraestructure matches the configuration I could make sure this was working and migrated as expected. 

---

__PR-008__ followed the same steps and workflow as the PR-007

---

## PR-009 — Migrate `iam` module (clean up wildcards, parameterize users)

This is the biggest migration so far. PR-009 moved 26 resources (6 roles + 8 policies + 10 role-attachments + 2 user-attachments) vs. 13 (storage) and 11 (network). It was also the first one with behavioral intent (tightening + gating), not just a pure move.

Also, in the legacy code there were 2 user names hardcoded, it was a "temporary" solution but got stuck in here until now. They were removed and now the values for those users were removed because they are no longer needed. 

Smoke test was done, using AWS CLI the SFN (Step Function) was started and I got the "SUCCEEDED" messag, meaning that I have the access from the new IAM module. 


## PR-010, 011, 012, 013, 014, 015 - Done, LakeFormation "The Elephant in the room" 

Everytyhing went ok from PR 10 to 15 except for one little thing the __PR-013__ "LakeFormation migration".
The main problemas that almost 2 years ago since I'm writting this note I wasn't able to understand how to code with terraform the LK access that allowed the __glue crawlers__ to write and read form the S3 buckets where the data is storage, also, how to make athena read from those buckets and use partion projections instead of crawlers to read that important data. 

So I went in the "easy mode" and I gave "full access" to the __glue-crawler-role__ that write the data in the buckets doing 2 things: 
   - Ignoring the "least previlige" rule
   - "Hardcoding" manually the needed access to allow the crawlers to write the data in the S3 buckets. 

Because lakeformation can work with "granular access" provided by LF or with "IAM access" that also allows LF access I wasn't sure how that worked at the time so I did with the own LF granular access. 
Now because the project is moving to a "Deploy and Replicate" mode, I have changed this to: 

- The access to the crawlers are still given via __"LF granular permissions"__ and now it is codable and can be replicated with terraform using __LF grants__.
- __Least privilege is real now:__ I removed the grant options (the right to re-grant permissions to others — a crawler never delegates) and the Super grant on the database (now just ALTER, CREATE_TABLE, DESCRIBE, DROP).
- I also had to stop writing permissions = ["ALL"]. LF expands Super server-side, so Terraform could never match its own read-back and wanted to replace the grant on every plan — revoking + re-granting the crawler's access each apply. Enumerating the six permissions is equivalent and stable.
- Smoke test was done and crawlers are running with no issues at all.


## Phase 1 is done!

Starting from a repo whose Terraform state had been lost and reconstructed, you now have:

One root (terraform/) with 10 modules — storage, network, iam, etl-lambda, etl-glue, catalog, orchestration, lake-formation, observability, and opt-in sagemaker.
Every resource under IaC, migrated without recreating a single one (all cross-state import + state rm).
Least-privilege IAM and Lake Formation, both proven by a green end-to-end pipeline run rather than assumed.
One weekly trigger instead of two — the pipeline was quietly running twice a week.
No console clicks required for a fresh deploy.-

---

## PR-16 Single source of truth: src/ layout

The legacy code was messy, splited between different directory files. Code was working just fine but it needed a better structure. Now all the code for the labmdas, extractor, parser and so on lives in one single "source of truth" that is `src/loteria` directory

## PR-017 — Parameterize hard-coded config

Before the change there use to be a very weak way to extract the data from the AWS Secrets Manager in the file [aws_secrets.py](./src/loteria/common/aws_secrets.py).

1) The name of the secret was hardcoded so trying to clone this repo into a new AWS Account would mean to editing python code, so now the name of the secret is parameterized. Same as the region, now can be set using a variable value and not hardcoded.

2) The ARN was beging extracted just "by accident" any value that only had ":::" was valid and being able to be considered as an ARN, that code was replaced by a real regex like so: `^arn:aws[a-z-]*:s3:::(?P<bucket>[^/]+)$` this one only extracts the value of the data only if it is an ARN and cannot be mistaken with "Scrape Do" token. (Scrape Do is a third party proxy server that helps to get the data using a Guatemala IP)

## PR-018 — Structured JSON logging

Previously in the code located in [./src/loteria/](./src/loteria/) had only a `print()` code in order to alert or notify the status of the process of the pipeline. This was changed by a logger using __stdlib-only__ (in order to make as simple as possible the code chage in Lambda and the code in general). 

Prints were replace using the script [logging_steup.py](./src/loteria/common/logging_setup.py).

[Step Function](./terraform/modules/orchestration/main.tf) passes its execution as `CORRELATION_ID` into both the Lambda payload and the Glue arguments, so every log line in one weekly run shares one id.

## PR-019 — Lambda Layer for heavy deps
Basically this was just an split between the lambda code and the dependencies (deps) this change does not makes more fast or slower the code or the lambda function. This is more "hygiene" of structure. Also, I discover that one of the dependencies (`charset_normalizer`) used for my lambda code was compiled just for Linux, so if this project by the time I'm writting this note, is clone into a Mac or Windows machine (assuming they are not using WSL2) the code won't really work. 

In my case it didn't show an error it was just digradated, the size of the file got bigger than it should but this was just look no the rule, this would actually break the thing is that `charset_normalizer` has serveral fallbacks, (now I'm running from a Windows machine) so that's why this still worked but it was just luck. 

This problem will be complete resolved in __PR-034__  so any OS will be able to compile this code with no issues related to deps.

Also, while doing some smoke test I notice that "today" July 20th an extraordinary lottery was played on last saturday, so the traffic in the loteria satalucia's web page has increace over the last days, so now we only get the CloudFlair's waiting room. As a quick fix for this kind of scenario I'm changing the extraction day from Monday to Thrusday. The best practice will be to create a fallback when this page is showing up in the Loteria's server, this is going to be done in __PR-026__ and __PR-031__.

## PR-020 — Glue Job upgrade spike (Glue 4.0 / Python 3.10)

In the [Roadmap](./roadmap.md) file I originally approved the idea to move the __glue version to 4.0__ and the __python version to 3.10__ this was one of the suggestions of Claude Opus 4.8, however when I was working on this the question surge like "Why move to this when python shell if the perfect fit?" Then I discover that this upgrade was going to make the transformer even slower rather than better of faster. This is prove that even when Claude suggest something is my responsability to dont just "copy/past" or code whatever Claude suggest. 

No changes done, the python shell job stays as it is. 

## Phase 2 Is Completed! 


## PR-021 — Gold table SQL definitions
The bronze layer are the `.txt.` files extracted each week form the lottery, the silver layer are the `.parquet` files obtained from the `.txt` files through a python job with the code of @transformer.py (which was refactor several months ago in order to create the silver gold). 

As a reminder the bronze layer is created with the extractor (the web scrapper) then the silver layer is created with then __transformer.py__ that creates the parquet files, and then a glue crawler scans the new data in order to annex it to AWS Athena and make the silver data queryable. 

So now using CTAS (Create Table As Select) 7 `sql` files were created and I'll ran manually in AWS CLI.
Then in PR-022 will be automated the process of reading and creating the tables for the gold layer.


## PR-022 — Wire Gold into Step Function
The CTAS were uploaded to S3 bucket in `sql/gold/` partition but now every time the pipeline runs the CTAS needs to be ran again in order to update the catalog, therefore a stepFuction was added in order to trigger a SQL that will drop the data and the table then, it runs the sql query for CTAS code. For query optimization the Gold layer also uses the `parquet` file. 

> Note 1: __Athena does not look a the extention file__, it actually reads from the end of the file content and looks at the firm with `PAR1` which is the parquet firm and then looks for the needed columns. 


> Note 2: __Why Lake Formation failed and the Gold run kept breaking?__ Because `silver/` is a registered LF location, Athena doesn't read those Parquet files with the role's own `s3:GetObject` — it asks LF to vend scoped temporary credentials, so every gold CTAS died on the read. The error wording is the tell: `no identity-based policy allows` means the IAM action is missing, whereas `Insufficient Lake Formation permission(s)` means the grant is. Fixing that alone wasn't enough, though — live prod showed the earlier `HIVE_PATH_ALREADY_EXISTS` fix had never been applied (stale Lambda code, no `DeleteObjectVersion`, bucket policy still exempting only root), so the failure would have simply moved back to the path check. The warning was __no identity-based policy allows__ so a `GetDataAccess` was required for the gold layer, so it was applied and now is working.

> Note 3: __What to do if I would have 1TB of data in the silver layer rather than a few MB?__ At that volume the full rebuild stops making sense: seven CTAS each scanning 1TB is ~$35 per run to re-read history you already computed, and the purge Lambda can't page through millions of object versions within its timeout. Iceberg replaces the whole drop-then-recreate dance with `MERGE INTO` / `INSERT OVERWRITE`, rewriting only the partitions the new sorteo actually touched — which deletes three moving parts outright: the purge Lambda, the PR-002 Deny exemption, and the S3 version hard-delete. Snapshot isolation also closes the window where the table simply doesn't exist between DROP and CTAS, and gives queryable time travel instead of approximating it with S3 versioning. The real cost is operational, not technical: Iceberg needs scheduled compaction and snapshot expiration or small files degrade the metadata, and silver must be partitioned by draw date so the engine can actually prune. Sensible trigger to migrate: when a run exceeds ~10 minutes or scanning reaches tens of GB.

## Phase 3 Is Completed!

## PR-023 — Log retention everywhere

When the CloudWatch log groups were created back then, they were created implicitly by AWS with no retention policy at all. So logs were accumulating for ever. This was resolved on this PR because a retention policy was added and set to be __30 days__ retention and also, I Imported the log groups for:

* etl-lambda
* orchestration
* etl-glue
* catalog 

Just one for the __StepFuctions__ log group is brand new and was created on this PR, the path is this one: `/aws/vendedlogs/states/lottery-etl-pipeline-prod`.

Smoke test that ensures StepFunction writes the data to the proper log group was done and it passed, now the retention for 30 days is set in the log groups and is working as expected. This improves the visibility of the pipeline status.

