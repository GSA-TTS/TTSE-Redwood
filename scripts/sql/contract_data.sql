CREATE TABLE IF NOT EXISTS {table} (
    contract_id         UUID         PRIMARY KEY,
    piid                VARCHAR(64)  NOT NULL,
    vendor_name         VARCHAR(200) NOT NULL,
    vendor_duns         CHAR(9)      NOT NULL,
    contract_value      NUMERIC(15, 2) NOT NULL,
    award_date          DATE         NOT NULL,
    contract_start_date DATE         NOT NULL,
    contract_end_date   DATE         NOT NULL,
    contract_type       VARCHAR(10)  NOT NULL
);
