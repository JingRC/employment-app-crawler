import 'package:flutter/material.dart';

import '../../../core/network/api_client.dart';
import '../../../shared/models/notification_item.dart';

class NotificationsPage extends StatefulWidget {
  const NotificationsPage({this.embedded = false, this.refreshToken = 0, super.key});

  final bool embedded;
  final int refreshToken;

  @override
  State<NotificationsPage> createState() => _NotificationsPageState();
}

class _NotificationsPageState extends State<NotificationsPage> {
  final ApiClient _apiClient = ApiClient();

  bool _loading = true;
  String? _error;
  List<NotificationItem> _notifications = const [];

  @override
  void initState() {
    super.initState();
    _loadNotifications();
  }

  @override
  void didUpdateWidget(covariant NotificationsPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.refreshToken != oldWidget.refreshToken) {
      _loadNotifications();
    }
  }

  Future<void> _loadNotifications() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final notifications = await _apiClient.fetchNotifications();
      if (!mounted) {
        return;
      }
      setState(() {
        _notifications = notifications;
      });
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _error = error.toString();
      });
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final body = _buildBody();
    if (widget.embedded) {
      return body;
    }
    return Scaffold(appBar: AppBar(title: const Text('通知')), body: body);
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_error!, textAlign: TextAlign.center),
              const SizedBox(height: 12),
              FilledButton(onPressed: _loadNotifications, child: const Text('重试')),
            ],
          ),
        ),
      );
    }

    if (_notifications.isEmpty) {
      return const Center(child: Text('暂无通知'));
    }

    return RefreshIndicator(
      onRefresh: _loadNotifications,
      child: ListView.separated(
        itemCount: _notifications.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          final item = _notifications[index];
          return ListTile(
            leading: Icon(
              item.isRead ? Icons.mark_email_read_outlined : Icons.notifications_active,
            ),
            title: Text(item.title),
            subtitle: Text(item.content),
            trailing: item.isRead ? null : const Chip(label: Text('未读')),
          );
        },
      ),
    );
  }
}
