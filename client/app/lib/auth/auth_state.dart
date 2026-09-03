import 'package:airwire_medium/airwire_medium.dart';
import 'package:equatable/equatable.dart';

sealed class AuthState extends Equatable {
  const AuthState();

  @override
  List<Object?> get props => [];
}

class AuthInitial extends AuthState {
  const AuthInitial();
}

class AuthUnauthenticated extends AuthState {
  const AuthUnauthenticated();
}

class AuthRedirecting extends AuthState {
  const AuthRedirecting();
}

class AuthAuthenticated extends AuthState {
  const AuthAuthenticated(this.medium);

  final OdnoklassnikiMedium medium;

  @override
  List<Object?> get props => [medium];
}

class AuthError extends AuthState {
  const AuthError(this.message);

  final String message;

  @override
  List<Object?> get props => [message];
}
