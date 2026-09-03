import 'package:equatable/equatable.dart';

sealed class AuthEvent extends Equatable {
  const AuthEvent();

  @override
  List<Object?> get props => [];
}

class AuthStarted extends AuthEvent {
  const AuthStarted();
}

class LoginRequested extends AuthEvent {
  const LoginRequested();
}

class AuthCallbackReceived extends AuthEvent {
  const AuthCallbackReceived(this.uri);

  final Uri uri;

  @override
  List<Object?> get props => [uri];
}

class LogoutRequested extends AuthEvent {
  const LogoutRequested();
}
