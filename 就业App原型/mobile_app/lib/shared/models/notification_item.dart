class NotificationItem {
  const NotificationItem({
    required this.notificationId,
    required this.title,
    required this.content,
    required this.isRead,
  });

  final int notificationId;
  final String title;
  final String content;
  final bool isRead;

  factory NotificationItem.fromJson(Map<String, dynamic> json) {
    return NotificationItem(
      notificationId: json['notification_id'] as int,
      title: (json['title'] ?? '') as String,
      content: (json['content'] ?? '') as String,
      isRead: (json['is_read'] ?? false) as bool,
    );
  }
}
