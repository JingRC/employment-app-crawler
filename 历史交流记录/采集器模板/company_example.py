from html_spider import HtmlSpider


class CompanyExampleSpider(HtmlSpider):
    source_code = "company_example"
    url = "https://company.example.com/careers"

    # 如果该公司页面结构与通用 HtmlSpider 不同，可重写 parse 方法
