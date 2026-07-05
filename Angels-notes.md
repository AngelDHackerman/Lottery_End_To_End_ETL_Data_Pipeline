# Angel's Notes 
> These are my personal notes, here I'll write the reason behind the tecnical desicions of why or how the project was developed, in order to create some sort of documentation for this project as well as a learning note for myself. 

* Remove the idea of creating 2 envs like "dev" and "prod" this was an old idea to show my skills as "devOps" but I want to get more focused in Data Quality and MLOps rather than "Hard Code Cloud DevOps"

**PR-001 — Repo hygiene baseline**
* Removed extra files in the "temp_files" that were test done previouly on this project.
* removed duplicated data in gitignore file
* added new virtual environment for python.
* Instead of using a setup.py or setup.cfg we are using now `pyproject.toml`
* added `makefile` in order to make things easier when deploying the architecture in a new pc or in local.
* Added `.pre-commit-cofing.yaml` file in order to check the quality of the code in terraform, python and jupyterNotebooks before sending it to the repo.
* Installed and enabled the command `gh` for "Git Hub CLI" so commands can be ran easly from the local terminal. 

**PR-002 - Inventory and protect prod buckets (no Terraform yet)** 
* The 2 json files in `/scripts/policies` are the bucket rules for protect the S3 buckets where the data is storage. 
* The `.txt` files in `/docs/inventory` are snapshots of current status in AWS about the data extracted with a readme file that explains why they exist. 
* Also, created a "safety belt" prior any refactor the file `scripts/00_inventory_and_protect.sh` 
    * Colors: allows the output termnal to show different colors based on "fail", "success" or any oter scenario when doing the dry run
    * Preconditions: verifies if the AWS profile, region and AWS command exists prior doing any change. 
    * Per-bucket work: creates and inventory of items in the buckets, enables the versioning on both buckets, adds the "deny policy" on both buckets.
    * Deny Delte Rule applies to all the users except for the __Admin__ in the AWS account. 
    * This was wrote in `.sh` file because these are pre-existing buckets, so __Terraform__ is not very good handling existing items, that's why the changes were done using __Bash__ and __AWS__.

**PR-003 - Move existing TF state to remote backend (no resource changes)**
On this PR the "refactor" is the pre-step move the terraform state file to a remote backend is done. 
* Created the `bootstrap/terrraform` directories in order to create the .tf files 
* dyamodb.tf, main.tf, and so on were created in order to set a S3 bucket in AWS and DynamoDB for blocking stated (as a real life production project)
* The local (as per now) is not scalable and just "toy project" like. HashiCorp's Cloud could be used but still we depend on "someone else's" service, so is a better idea to centralize everything in AWS with all the protection rules for that bucket and blcoking the state file with dynamoDB with a ver low cost. 

**PR-004 Move existing TF state to remote backend (no resource changes)**
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

**PR-005 — Import existing buckets into Terraform with `prevent_destroy`** 
When I started doing this project I cretaed several buckets manually one of those were `lottery-partitioned-storage-prod` and `lottery-data-simple-prod` one for "Hive-style" data (better to use with Athena and SQL queries) and the other one for "Simple checks" better for run notebooks and do manual verificationa about the extracted data of each weekly lottery. 
The problem is that originally I didn't import them so I left the terraform code commented just to remember myself about that "buckets exist but were not created in here". 

Now they were officially imported to the terraform code and are managed by Terraform and will "live" in the S3 remote backend. Also, for consistency the were renamed in the terraform code to:

| | Terraform label (the address in HCL) | Real AWS bucket name (`bucket = "..."`) |
|---|---|---|
| **Before** | `aws_s3_bucket.lottery_raw_data` | `lottery-partitioned-storage-prod` |
| **After** | `aws_s3_bucket.lottery_partitioned` | `lottery-partitioned-storage-prod` ← *unchanged* |
| **Before** | `aws_s3_bucket.lottery_data_simple` | `lottery-data-simple-prod` |
| **After** | `aws_s3_bucket.lottery_simple` | `lottery-data-simple-prod` ← *unchanged* |
