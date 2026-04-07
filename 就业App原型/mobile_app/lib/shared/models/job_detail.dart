class JobDetail {
  const JobDetail({
    required this.jobId,
    required this.companyId,
    required this.title,
    required this.companyName,
    required this.cityName,
    required this.districtName,
    required this.salaryText,
    required this.degreeText,
    required this.experienceText,
    required this.descriptionText,
    required this.officialApplyUrl,
  });

  final int jobId;
  final int companyId;
  final String title;
  final String companyName;
  final String cityName;
  final String districtName;
  final String salaryText;
  final String degreeText;
  final String experienceText;
  final String descriptionText;
  final String officialApplyUrl;

  factory JobDetail.fromJson(Map<String, dynamic> json) {
    return JobDetail(
      jobId: json['job_id'] as int,
      companyId: json['company_id'] as int? ?? 0,
      title: (json['title'] ?? '') as String,
      companyName: (json['company_name'] ?? '') as String,
      cityName: (json['city_name'] ?? '') as String,
      districtName: (json['district_name'] ?? '') as String,
      salaryText: (json['salary_text'] ?? '') as String,
      degreeText: (json['degree_text'] ?? '') as String,
      experienceText: (json['experience_text'] ?? '') as String,
      descriptionText: (json['description_text'] ?? '') as String,
      officialApplyUrl: (json['official_apply_url'] ?? '') as String,
    );
  }
}
