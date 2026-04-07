from company_example import CompanyExampleSpider
from deduplicator import build_content_hash, build_unique_hash
from normalizer import normalize_record


def main() -> None:
    spider = CompanyExampleSpider()
    records = spider.run()

    for record in records:
        record = normalize_record(record)
        unique_hash = build_unique_hash(record)
        content_hash = build_content_hash(record)
        print(record)
        print("unique_hash=", unique_hash)
        print("content_hash=", content_hash)


if __name__ == "__main__":
    main()
