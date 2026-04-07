import 'package:flutter/material.dart';

import 'app/shell/app_shell.dart';

void main() {
  runApp(const JobAggregatorApp());
}

class JobAggregatorApp extends StatelessWidget {
  const JobAggregatorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Job Aggregator',
      theme: ThemeData(colorSchemeSeed: Colors.blue, useMaterial3: true),
      home: const AppShell(),
    );
  }
}
