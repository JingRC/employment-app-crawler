class JobItem {
  const JobItem({
    required this.jobId,
    required this.title,
    required this.companyName,
    required this.cityName,
    required this.salaryText,
    required this.officialApplyUrl,
  });

  final int jobId;
  final String title;
  final String companyName;
  final String cityName;
  final String salaryText;
  final String officialApplyUrl;

  factory JobItem.fromJson(Map<String, dynamic> json) {
    return JobItem(
      jobId: json['job_id'] as int,
      title: (json['title'] ?? '') as String,
      companyName: (json['company_name'] ?? '') as String,
      cityName: (json['city_name'] ?? '') as String,
      salaryText: (json['salary_text'] ?? '') as String,
      officialApplyUrl: (json['official_apply_url'] ?? '') as String,
    );
  }
}
