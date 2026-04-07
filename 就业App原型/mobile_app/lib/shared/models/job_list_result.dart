import 'job_item.dart';

class JobListResult {
  const JobListResult({
    required this.page,
    required this.pageSize,
    required this.total,
    required this.items,
  });

  final int page;
  final int pageSize;
  final int total;
  final List<JobItem> items;

  bool get hasMore => page * pageSize < total;

  factory JobListResult.fromJson(Map<String, dynamic> json) {
    final rawItems = (json['items'] as List<dynamic>? ?? <dynamic>[])
        .cast<Map<String, dynamic>>();
    return JobListResult(
      page: json['page'] as int? ?? 1,
      pageSize: json['page_size'] as int? ?? rawItems.length,
      total: json['total'] as int? ?? rawItems.length,
      items: rawItems.map(JobItem.fromJson).toList(),
    );
  }
}