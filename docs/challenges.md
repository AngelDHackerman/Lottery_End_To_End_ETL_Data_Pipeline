## 🚧 Challenges Faced and How They Were Overcome

### 1. ❌ No Access to Historical Data
**Problem:** The official website of Lotería Santa Lucía does not preserve historical draw data. Once a draw expires, the info is gone.

**Solution:** I built a custom web scraper that extracts and stores draw data weekly. By running it frequently and storing results in AWS S3, I am building a permanent dataset from scratch — something no one else has done publicly in Guatemala.

---

### 2. 🌐 VPC Connectivity Issues
**Problem:** My initial SageMaker setup could not connect to S3 due to improper VPC endpoint configuration. SageMaker kernels would freeze or time out when accessing data.

**Solution:** After deep debugging and rebuilding the network, I implemented a correct **S3 Gateway Endpoint** in a clean VPC. This allowed SageMaker Studio to access S3 without internet or NAT, reducing latency and cost.

---

### 3. 🔄 Preventing Duplicate Work
**Problem:** I needed to avoid reprocessing draws that were already handled to save compute time and S3 storage.

**Solution:** I implemented an **idempotent check** — before scraping, the script verifies whether a processed `.parquet` file already exists in the destination bucket.

---

### 4. 💸 Cost vs Complexity Trade-offs
**Problem:** Including Athena and Glue inside the VPC required creating **Interface Endpoints**, which generate hourly and per-GB charges.

**Solution:** I documented the decision to leave Glue, Athena, and QuickSight **outside the VPC**, connecting only SageMaker via S3 Gateway Endpoint. This hybrid architecture keeps costs minimal while preserving security and scalability.

---

### 5. 🔒 Lake Formation Permissions for Glue Crawlers
**Problem:** Initially, AWS Glue Crawlers faced persistent "Insufficient Lake Formation permission(s)" errors when attempting to discover and catalog data in S3 via Lake Formation. This issue manifested in several stages, blocking the creation and update of table metadata.

**Solution:** The problem was systematically addressed by configuring granular Lake Formation permissions:
    * **Database-Level Permissions:** Granted `Create table`, `Alter`, `Drop`, and `Describe` permissions on `lottery_santalucia_db` to the `glue-crawler-role`.
    * **Table-Level Permissions:** Granted `Super` permission on "All tables" within `lottery_santalucia_db` to the `glue-crawler-role`.
    * **S3 Data Location Access:** Ensured `s3://lottery-partitioned-storage-prod/processed` was registered in Lake Formation with `AWSServiceRoleForLakeFormationDataAccess`. Crucially, `Data location access` was explicitly granted to the `glue-crawler-role` for the specific data sub-paths: `s3://lottery-partitioned-storage-prod/processed/premios/` and `s3://lottery-partitioned-storage-prod/processed/sorteos/`. This resolved errors directly related to S3 path access.
    * **`IAMAllowedPrincipals` Compatibility:** Granted `Create table`, `Alter`, `Describe`, and `Drop` permissions on `lottery_santalucia_db` to the `IAMAllowedPrincipals` group. This was essential for compatibility with Glue's default behavior in Lake Formation's "Hybrid access mode" (where "Make Lake Formation permissions effective immediately" was unchecked).
    * **Permission Propagation:** After each permission change, a waiting period (5-30 minutes) was observed to allow for full propagation across Lake Formation and Glue services, which is vital for new permissions to take effect.

**Outcome:** After these comprehensive permission adjustments and waiting for propagation, the Glue Crawlers successfully ran and cataloged the `premios_premios` and `sorteos_sorteos` tables in the Glue Data Catalog.

---

### 6. 🛑 IP Block from Lotería Website (Geo-Restricted Access)
**Problem:** The official website of Lotería Santa Lucía implemented anti-bot measures that silently blocked repeated scraping requests coming from U.S.-based IP addresses — particularly those used by AWS Lambda or EC2 from the `us-east-1` region. Although the scraper did not raise explicit HTTP errors, the responses were incomplete or empty, causing the ingestion pipeline to silently fail.

**Solution:** After thorough testing with tools like `curl` and browser headers, the issue was identified as **IP-based blocking**. To circumvent this, I deployed a lightweight **proxy in Latin America** to serve as an intermediary between AWS Lambda and the target site. By routing traffic through a regionally-appropriate IP **(Using a Proxy service)**, the website responded as expected, restoring full scraper functionality.

**Outcome:** This solved the silent data loss problem and ensured reliable, location-compliant data extraction on every weekly run.

---

### 7. 🐍 Pandas Library Too Heavy for AWS Lambda Functions
**Problem:** The transformation logic for the lottery data heavily relies on **Pandas**, which exceeds the AWS Lambda deployment package size limits. Even when using Lambda Layers, the total size of the environment (≈420 MB decompressed) caused failures, especially during cold starts and dependency resolution.

**Solution:** Instead of trying to slim down the Lambda runtime, I migrated the transformation logic to **AWS Glue Python Shell Jobs**. Glue allows importing `.zip` scripts and supports Pandas natively without size constraints. I refactored the transformer into a callable `__main__.py` entrypoint, bundled it in a `.zip`, uploaded it to S3, and executed it using Glue with the proper IAM roles and permissions.

**Outcome:** The Glue Job ran successfully, transforming raw files and uploading `.parquet` outputs to the partitioned S3 structure. This shift also paved the way for deeper serverless orchestration using Step Functions and EventBridge.
