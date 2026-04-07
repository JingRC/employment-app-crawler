import 'package:flutter/material.dart';

import '../../features/favorites/pages/favorites_page.dart';
import '../../features/jobs/pages/job_list_page.dart';
import '../../features/notifications/pages/notifications_page.dart';

class AppRouter {
  static const jobs = '/';
  static const favorites = '/favorites';
  static const notifications = '/notifications';

  static final routes = <String, WidgetBuilder>{
    jobs: (_) => const JobListPage(),
    favorites: (_) => const FavoritesPage(),
    notifications: (_) => const NotificationsPage(),
  };
}
