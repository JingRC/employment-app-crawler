class NotificationItem {
  const NotificationItem({
    required this.notificationId,
    required this.notificationType,
    required this.actionSource,
    required this.actionSourceName,
    required this.title,
    required this.content,
    required this.isRead,
    required this.createdAt,
    required this.relatedJobId,
  });

  final int notificationId;
  final String notificationType;
  final String actionSource;
  final String actionSourceName;
  final String title;
  final String content;
  final bool isRead;
  final String createdAt;
  final int? relatedJobId;

  factory NotificationItem.fromJson(Map<String, dynamic> json) {
    return NotificationItem(
      notificationId: json['notification_id'] as int,
      notificationType: (json['notification_type'] ?? '') as String,
      actionSource: (json['action_source'] ?? '') as String,
      actionSourceName: (json['action_source_name'] ?? '') as String,
      title: (json['title'] ?? '') as String,
      content: (json['content'] ?? '') as String,
      isRead: (json['is_read'] ?? false) as bool,
      createdAt: (json['created_at'] ?? '') as String,
      relatedJobId: json['related_job_id'] as int?,
    );
  }
}
