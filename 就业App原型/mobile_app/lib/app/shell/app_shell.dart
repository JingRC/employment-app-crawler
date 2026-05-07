import 'package:flutter/material.dart';

import '../../features/favorites/pages/favorites_page.dart';
import '../../features/jobs/pages/job_list_page.dart';
import '../../features/notifications/pages/notifications_page.dart';
import '../../core/network/api_client.dart';

class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  final ApiClient _apiClient = ApiClient();

  int _currentIndex = 0;
  int _favoritesRefreshToken = 0;
  int _notificationsRefreshToken = 0;
  int _unreadNotifications = 0;

  static const List<String> _titles = <String>['职位', '收藏', '通知'];

  @override
  void initState() {
    super.initState();
    _refreshNotificationBadge();
  }

  Future<void> _refreshNotificationBadge() async {
    try {
      final stats = await _apiClient.fetchNotificationStats();
      if (!mounted) {
        return;
      }
      setState(() {
        _unreadNotifications = stats.unread;
      });
    } catch (_) {
    }
  }

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      const JobListPage(embedded: true),
      FavoritesPage(embedded: true, refreshToken: _favoritesRefreshToken),
      NotificationsPage(
        embedded: true,
        refreshToken: _notificationsRefreshToken,
        onUnreadChanged: (count) {
          if (!mounted) {
            return;
          }
          setState(() {
            _unreadNotifications = count;
          });
        },
      ),
    ];

    return Scaffold(
      appBar: AppBar(title: Text(_titles[_currentIndex])),
      body: IndexedStack(index: _currentIndex, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (index) {
          setState(() {
            _currentIndex = index;
            if (index == 1) {
              _favoritesRefreshToken++;
            }
            if (index == 2) {
              _notificationsRefreshToken++;
              _refreshNotificationBadge();
            }
          });
        },
        destinations: [
          NavigationDestination(icon: Icon(Icons.work_outline), label: '职位'),
          const NavigationDestination(icon: Icon(Icons.favorite_border), label: '收藏'),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: _unreadNotifications > 0,
              label: Text(_unreadNotifications > 99 ? '99+' : '$_unreadNotifications'),
              child: const Icon(Icons.notifications_none),
            ),
            label: '通知',
          ),
        ],
      ),
    );
  }
}