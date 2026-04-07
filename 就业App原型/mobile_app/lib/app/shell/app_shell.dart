import 'package:flutter/material.dart';

import '../../features/favorites/pages/favorites_page.dart';
import '../../features/jobs/pages/job_list_page.dart';
import '../../features/notifications/pages/notifications_page.dart';

class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _currentIndex = 0;
  int _favoritesRefreshToken = 0;
  int _notificationsRefreshToken = 0;

  static const List<String> _titles = <String>['职位', '收藏', '通知'];

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      const JobListPage(embedded: true),
      FavoritesPage(embedded: true, refreshToken: _favoritesRefreshToken),
      NotificationsPage(embedded: true, refreshToken: _notificationsRefreshToken),
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
            }
          });
        },
        destinations: const [
          NavigationDestination(icon: Icon(Icons.work_outline), label: '职位'),
          NavigationDestination(icon: Icon(Icons.favorite_border), label: '收藏'),
          NavigationDestination(icon: Icon(Icons.notifications_none), label: '通知'),
        ],
      ),
    );
  }
}