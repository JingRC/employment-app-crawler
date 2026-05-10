class JobTrackingItem {
  const JobTrackingItem({
    required this.jobId,
    required this.title,
    required this.companyName,
    required this.cityName,
    required this.salaryText,
    required this.sourceUrl,
    required this.sourceCode,
    required this.sourceName,
    required this.status,
    required this.trackingStatus,
    required this.notes,
    required this.appliedAt,
    required this.interviewAt,
    required this.offerAt,
    required this.resultAt,
    required this.resultStatus,
    required this.createdAt,
    required this.updatedAt,
  });

  final int jobId;
  final String title;
  final String companyName;
  final String cityName;
  final String salaryText;
  final String sourceUrl;
  final String sourceCode;
  final String sourceName;
  final String status;
  final String trackingStatus;
  final String notes;
  final String appliedAt;
  final String interviewAt;
  final String offerAt;
  final String resultAt;
  final String resultStatus;
  final String createdAt;
  final String updatedAt;

  factory JobTrackingItem.fromJson(Map<String, dynamic> json) {
    return JobTrackingItem(
      jobId: json['job_id'] as int,
      title: (json['title'] ?? '') as String,
      companyName: (json['company_name'] ?? '') as String,
      cityName: (json['city_name'] ?? '') as String,
      salaryText: (json['salary_text'] ?? '') as String,
      sourceUrl: (json['source_url'] ?? '') as String,
      sourceCode: (json['source_code'] ?? '') as String,
      sourceName: (json['source_name'] ?? json['source_code'] ?? '') as String,
      status: (json['status'] ?? 'active') as String,
      trackingStatus: (json['tracking_status'] ?? 'saved') as String,
      notes: (json['notes'] ?? '') as String,
      appliedAt: (json['applied_at'] ?? '') as String,
      interviewAt: (json['interview_at'] ?? '') as String,
      offerAt: (json['offer_at'] ?? '') as String,
      resultAt: (json['result_at'] ?? '') as String,
      resultStatus: (json['result_status'] ?? '') as String,
      createdAt: (json['created_at'] ?? '') as String,
      updatedAt: (json['updated_at'] ?? '') as String,
    );
  }
}
