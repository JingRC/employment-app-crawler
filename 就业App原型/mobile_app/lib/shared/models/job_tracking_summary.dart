class JobTrackingSummary {
  const JobTrackingSummary({
    required this.saved,
    required this.applied,
    required this.interview,
    required this.offer,
    required this.accepted,
    required this.rejected,
  });

  final int saved;
  final int applied;
  final int interview;
  final int offer;
  final int accepted;
  final int rejected;

  int get total => saved + applied + interview + offer + accepted + rejected;

  factory JobTrackingSummary.fromJson(Map<String, dynamic> json) {
    return JobTrackingSummary(
      saved: (json['saved'] ?? 0) as int,
      applied: (json['applied'] ?? 0) as int,
      interview: (json['interview'] ?? 0) as int,
      offer: (json['offer'] ?? 0) as int,
      accepted: (json['accepted'] ?? 0) as int,
      rejected: (json['rejected'] ?? 0) as int,
    );
  }
}
